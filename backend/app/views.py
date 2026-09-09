import base64
import json
import math
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.mail import send_mail
from django.db import connection
from django.db.models import Count, Q
from django.db.utils import OperationalError
from django.templatetags.static import static
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.conf import settings

from .forms import ExpenseForm, OwnerProfileForm, VehicleForm
from .models import Booking, Expense, OwnerProfile, Vehicle, VehicleImage


def _partners_queryset():
    return (
        OwnerProfile.objects.annotate(
            total_vehicles=Count("vehicles", filter=Q(vehicles__is_verified=True)),
            cars_count=Count(
                "vehicles",
                filter=Q(vehicles__category=Vehicle.Category.CAR, vehicles__is_verified=True),
            ),
            bikes_count=Count(
                "vehicles",
                filter=Q(vehicles__category=Vehicle.Category.BIKE, vehicles__is_verified=True),
            ),
        )
        .filter(total_vehicles__gt=0, is_verified=True, user__is_active=True)
        .select_related("user")
        .order_by("-total_vehicles", "business_name")
    )


def _vehicle_image_url(vehicle):
    first_gallery_image = vehicle.images.first()
    if first_gallery_image:
        return first_gallery_image.image.url
    if vehicle.photo:
        return vehicle.photo.url
    if vehicle.photo_url:
        return vehicle.photo_url

    label = f"{vehicle.brand} {vehicle.name}".lower()

    # Match common names/brands to better default images.
    if any(token in label for token in ["bmw", "x7", "x5"]):
        return static("assets/BMW.png")
    if any(token in label for token in ["hunter", "enfield", "classic", "duke", "r15", "apache", "pulsar"]):
        return static("assets/hunter.png")
    if any(token in label for token in ["creta", "city", "verna", "baleno", "harrier", "xuv"]):
        return static("assets/hunter2.png")
    return static("assets/logo.jpg")


OTP_EXPIRY_SECONDS = 300


def _otp_session_store(request):
    store = request.session.get("otp_store")
    if not isinstance(store, dict):
        store = {}
    return store


def _otp_verified_map(request):
    verified = request.session.get("otp_verified")
    if not isinstance(verified, dict):
        verified = {}
    return verified


def _otp_verified_key(purpose, channel, target):
    return f"{purpose}:{channel}:{str(target).strip().lower()}"


def _mark_otp_verified(request, purpose, channel, target):
    verified = _otp_verified_map(request)
    verified[_otp_verified_key(purpose, channel, target)] = int(time.time())
    request.session["otp_verified"] = verified
    request.session.modified = True


def _is_otp_verified(request, purpose, channel, target):
    if not target:
        return False
    verified = _otp_verified_map(request)
    ts = verified.get(_otp_verified_key(purpose, channel, target))
    if not ts:
        return False
    return int(time.time()) - int(ts) <= OTP_EXPIRY_SECONDS


def _create_otp(request, purpose, channel, target):
    otp_id = uuid.uuid4().hex
    code = f"{random.randint(0, 999999):06d}"
    store = _otp_session_store(request)
    store[otp_id] = {
        "purpose": str(purpose),
        "channel": str(channel),
        "target": str(target).strip(),
        "code": code,
        "expires_at": int(time.time()) + OTP_EXPIRY_SECONDS,
        "verified": False,
    }
    request.session["otp_store"] = store
    request.session.modified = True
    return otp_id, code


def _normalize_indian_phone(raw_phone):
    digits = "".join(ch for ch in str(raw_phone or "") if ch.isdigit())
    if digits.startswith("91") and len(digits) >= 12:
        local = digits[-10:]
    elif len(digits) >= 10:
        local = digits[-10:]
    else:
        return ""
    return f"+91{local}"


def _send_email_otp(target, code):
    if not settings.EMAIL_HOST or not settings.EMAIL_HOST_USER:
        print(f"[DEMO EMAIL OTP] {target}: {code}")
        return True, f"Demo mode: Your OTP is {code}"

    try:
        send_mail(
            subject="RoyalWheels OTP Verification",
            message=f"Your OTP is {code}. It is valid for 5 minutes.",
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@royalwheels.local"),
            recipient_list=[target],
            fail_silently=False,
        )
        return True, "OTP sent to email."
    except Exception as exc:
        print(f"[EMAIL SEND ERROR] {exc} -> Demo OTP: {code}")
        return True, f"Demo mode: Your OTP is {code}"


def _send_phone_otp(target, code):
    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN or not settings.TWILIO_FROM_NUMBER:
        print(f"[DEMO SMS OTP] {target}: {code}")
        return True, f"Demo mode: Your OTP is {code}"

    api_url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Messages.json"
    payload = urllib.parse.urlencode(
        {
            "From": settings.TWILIO_FROM_NUMBER,
            "To": target,
            "Body": f"Your RoyalWheels OTP is {code}. Valid for 5 minutes.",
        }
    ).encode("utf-8")

    auth_raw = f"{settings.TWILIO_ACCOUNT_SID}:{settings.TWILIO_AUTH_TOKEN}".encode("utf-8")
    auth_header = base64.b64encode(auth_raw).decode("ascii")

    request_obj = urllib.request.Request(api_url, data=payload, method="POST")
    request_obj.add_header("Authorization", f"Basic {auth_header}")
    request_obj.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(request_obj, timeout=12) as response:
            status_code = getattr(response, "status", 200)
            if status_code < 200 or status_code >= 300:
                return True, f"Demo mode: Your OTP is {code}"
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        print(f"[SMS SEND ERROR] {exc} -> Demo OTP: {code}")
        return True, f"Demo mode: Your OTP is {code}"

    return True, "OTP sent to phone."


def home(request):
    partners_qs = _partners_queryset().order_by("-created_at", "-total_vehicles", "business_name")
    return render(
        request,
        "Home_index.html",
        {
            "total_vehicles": Vehicle.objects.filter(
                is_verified=True,
                owner__is_verified=True,
                owner__user__is_active=True,
            ).count(),
            "total_partners": partners_qs.count(),
            "partners": partners_qs[:6],
        },
    )


def cars_page(request):
    cars = Vehicle.objects.select_related("owner").prefetch_related("images").filter(
        category=Vehicle.Category.CAR,
        is_verified=True,
        owner__is_verified=True,
        owner__user__is_active=True,
    )
    for vehicle in cars:
        vehicle.display_image_url = _vehicle_image_url(vehicle)
        vehicle.gallery_urls = [img.image.url for img in vehicle.images.all()[:4]]
    return render(request, "Car.html", {"vehicles": cars})


def bikes_page(request):
    bikes = Vehicle.objects.select_related("owner").prefetch_related("images").filter(
        category=Vehicle.Category.BIKE,
        is_verified=True,
        owner__is_verified=True,
        owner__user__is_active=True,
    )
    for vehicle in bikes:
        vehicle.display_image_url = _vehicle_image_url(vehicle)
        vehicle.gallery_urls = [img.image.url for img in vehicle.images.all()[:4]]
    return render(request, "Bikes.html", {"vehicles": bikes})


def partners_page(request):
    return render(request, "AllPartners.html", {"partners": _partners_queryset()})


def my_bookings_page(request):
    return render(request, "MyBooking.html")


def profile_page(request):
    return render(request, "profile.html")


def login_page(request):
    return render(request, "login.html")


def user_forgot_password_page(request):
    return render(request, "forgot_password.html")


def signup_page(request):
    return render(request, "signup.html")


def book_now_page(request):
    return render(request, "Book_now.html")


def payment_page(request):
    return render(request, "payment.html")


def admin_login_page(request):
    if request.user.is_authenticated:
        return redirect("owner_dashboard")

    if request.method == "POST":
        username_or_email = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        user = authenticate(request, username=username_or_email, password=password)

        if user is None and "@" in username_or_email:
            existing_user = get_user_model().objects.filter(email__iexact=username_or_email).first()
            if existing_user:
                user = authenticate(request, username=existing_user.username, password=password)

        if user is None:
            messages.error(request, "Invalid username/email or password.")
        else:
            login(request, user)
            return redirect("owner_dashboard")

    return render(request, "admin/admin_login.html")


def admin_forgot_password_page(request):
    if request.user.is_authenticated:
        return redirect("owner_dashboard")

    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        phone = _normalize_indian_phone(request.POST.get("phone"))
        password = request.POST.get("password") or ""
        confirm_password = request.POST.get("confirm_password") or ""

        if not email or not phone or not password or not confirm_password:
            messages.error(request, "Please fill all fields.")
            return render(request, "admin/admin_forgot_password.html")

        if password != confirm_password:
            messages.error(request, "New password and confirm password do not match.")
            return render(request, "admin/admin_forgot_password.html")

        user_model = get_user_model()
        user = user_model.objects.filter(email__iexact=email).first()
        owner_profile = OwnerProfile.objects.filter(user=user).first() if user else None
        if user is None or owner_profile is None:
            messages.error(request, "No admin account found for this email.")
            return render(request, "admin/admin_forgot_password.html")

        if _normalize_indian_phone(owner_profile.phone_number) != phone:
            messages.error(request, "Provided phone number does not match this admin account.")
            return render(request, "admin/admin_forgot_password.html")

        if not _is_otp_verified(request, "admin_forgot", "email", email):
            messages.error(request, "Please verify email OTP first.")
            return render(request, "admin/admin_forgot_password.html")

        if not _is_otp_verified(request, "admin_forgot", "phone", phone):
            messages.error(request, "Please verify phone OTP first.")
            return render(request, "admin/admin_forgot_password.html")

        try:
            validate_password(password, user=user)
        except ValidationError as exc:
            for message in exc.messages:
                messages.error(request, message)
            return render(request, "admin/admin_forgot_password.html")

        user.set_password(password)
        user.save(update_fields=["password"])
        messages.success(request, "Password reset successful. Please login.")
        return redirect("admin_login_page")

    return render(request, "admin/admin_forgot_password.html")


def admin_signup_page(request):
    if request.user.is_authenticated:
        return redirect("owner_dashboard")

    if request.method == "POST":
        shop_name = (request.POST.get("shop") or "").strip()
        owner_name = (request.POST.get("owner") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        phone = _normalize_indian_phone(request.POST.get("phone"))
        address = (request.POST.get("address") or "").strip()
        gst = (request.POST.get("gst") or "").strip()
        password = request.POST.get("password") or ""

        if not shop_name or not owner_name or not email or not phone or not password:
            messages.error(request, "Shop name, owner name, email, phone and password are required.")
            return render(request, "admin/admin_signup.html")

        if not _is_otp_verified(request, "admin_signup", "email", email):
            messages.error(request, "Please verify email OTP first.")
            return render(request, "admin/admin_signup.html")

        if not _is_otp_verified(request, "admin_signup", "phone", phone):
            messages.error(request, "Please verify phone OTP first.")
            return render(request, "admin/admin_signup.html")

        user_model = get_user_model()
        if user_model.objects.filter(email__iexact=email).exists():
            messages.error(request, "A user with this email already exists.")
            return render(request, "admin/admin_signup.html")

        base_username = "".join(ch for ch in owner_name.lower().replace(" ", "_") if ch.isalnum() or ch == "_")
        username = base_username or "shopkeeper"
        count = 1
        while user_model.objects.filter(username=username).exists():
            username = f"{base_username or 'shopkeeper'}{count}"
            count += 1

        user = user_model.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=owner_name,
        )
        OwnerProfile.objects.create(
            user=user,
            business_name=shop_name,
            phone_number=phone,
            address=address,
            license_number=gst,
            profile_photo_url=(request.POST.get("photo_url") or "").strip(),
        )
        messages.success(request, "Shopkeeper account created. Please login.")
        return redirect("admin_login_page")

    return render(request, "admin/admin_signup.html")


@login_required
def shopkeeper_logout(request):
    logout(request)
    messages.success(request, "You have been logged out.")
    return redirect("admin_login_page")


@login_required
def owner_dashboard_api(request):
    owner = get_object_or_404(OwnerProfile, user=request.user)
    data = {
        "owner": owner.business_name,
        "vehicles": owner.vehicles.count(),
        "active_bookings": owner.bookings.filter(status=Booking.Status.CONFIRMED).count(),
        "completed_bookings": owner.bookings.filter(status=Booking.Status.COMPLETED).count(),
        "total_revenue": float(owner.total_revenue),
        "total_expenses": float(owner.total_expenses),
        "total_profit": float(owner.total_profit),
    }
    return JsonResponse(data)


@login_required
def owner_dashboard(request):
    owner = OwnerProfile.objects.filter(user=request.user).first()
    legacy_booking_schema = False
    deferred_legacy_fields = (
        "customer_email",
        "customer_address",
        "customer_lpu_id",
        "customer_license_number",
        "customer_age",
        "driving_license_doc",
        "student_id_doc",
    )
    try:
        with connection.cursor() as cursor:
            description = connection.introspection.get_table_description(cursor, Booking._meta.db_table)
            legacy_booking_schema = not any(col.name == "customer_email" for col in description)
    except OperationalError:
        # If introspection fails, keep dashboard resilient by using only legacy-safe columns.
        legacy_booking_schema = True

    booking_base_qs = owner.bookings.select_related("vehicle") if owner else None
    if legacy_booking_schema and booking_base_qs is not None:
        booking_base_qs = booking_base_qs.defer(*deferred_legacy_fields)

    active_rentals = (
        booking_base_qs
        .filter(status=Booking.Status.CONFIRMED)
        .order_by("start_date")[:10]
        if booking_base_qs is not None
        else []
    )
    pending_bookings = (
        booking_base_qs
        .filter(status=Booking.Status.PENDING)
        .order_by("-created_at")[:10]
        if booking_base_qs is not None
        else []
    )
    return render(
        request,
        "management/dashboard.html",
        {
            "owner": owner,
            "vehicles_count": owner.vehicles.count() if owner else 0,
            "active_bookings": (
                owner.bookings.filter(status=Booking.Status.CONFIRMED).count() if owner else 0
            ),
            "completed_bookings": (
                owner.bookings.filter(status=Booking.Status.COMPLETED).count() if owner else 0
            ),
            "total_revenue": owner.total_revenue if owner else Decimal("0.00"),
            "total_expenses": owner.total_expenses if owner else Decimal("0.00"),
            "total_profit": owner.total_profit if owner else Decimal("0.00"),
            "active_rentals_rows": active_rentals,
            "pending_bookings": pending_bookings,
            "legacy_booking_schema": legacy_booking_schema,
        },
    )


@login_required
@require_POST
def booking_decision(request, booking_id):
    owner = get_object_or_404(OwnerProfile, user=request.user)
    booking = get_object_or_404(Booking, id=booking_id, owner=owner)
    decision = (request.POST.get("decision") or "").lower()

    if decision == "accept":
        booking.status = Booking.Status.CONFIRMED
        booking.vehicle.is_available = False
        booking.vehicle.save(update_fields=["is_available", "updated_at"])
        booking.save(update_fields=["status", "updated_at"])
        messages.success(request, "Booking accepted.")
    elif decision == "reject":
        booking.status = Booking.Status.CANCELLED
        booking.vehicle.is_available = True
        booking.vehicle.save(update_fields=["is_available", "updated_at"])
        booking.save(update_fields=["status", "updated_at"])
        messages.success(request, "Booking rejected.")
    elif decision == "complete":
        if booking.status != Booking.Status.CONFIRMED:
            messages.error(request, "Only confirmed bookings can be completed.")
        else:
            booking.vehicle.is_available = True
            booking.vehicle.save(update_fields=["is_available", "updated_at"])
            booking.mark_completed()
            messages.success(request, "Booking marked completed and vehicle is available again.")
    else:
        messages.error(request, "Invalid booking action.")

    referer = request.META.get("HTTP_REFERER", "")
    if "/management/bookings/" in referer:
        return redirect("booking_manage")
    return redirect("owner_dashboard")


@login_required
def owner_profile_manage(request):
    owner = OwnerProfile.objects.filter(user=request.user).first()
    form = OwnerProfileForm(request.POST or None, request.FILES or None, instance=owner)
    if request.method == "POST" and form.is_valid():
        profile = form.save(commit=False)
        profile.user = request.user
        profile.save()
        messages.success(request, "Profile saved successfully.")
        return redirect("owner_profile_manage")
    return render(
        request,
        "management/profile_manage.html",
        {"form": form, "owner": owner},
    )


@login_required
def vehicle_manage(request):
    owner = OwnerProfile.objects.filter(user=request.user).first()
    if not owner:
        messages.error(request, "Create your owner profile first.")
        return redirect("owner_profile_manage")
    form = VehicleForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        vehicle = form.save(commit=False)
        vehicle.owner = owner
        vehicle.save()
        for uploaded in request.FILES.getlist("gallery_images"):
            VehicleImage.objects.create(vehicle=vehicle, image=uploaded)
        messages.success(request, "Vehicle added successfully.")
        return redirect("vehicle_manage")

    vehicles = owner.vehicles.prefetch_related("images").all()
    return render(
        request,
        "management/vehicle_manage.html",
        {"form": form, "vehicles": vehicles, "owner": owner},
    )


@login_required
def vehicle_edit(request, vehicle_id):
    owner = OwnerProfile.objects.filter(user=request.user).first()
    if not owner:
        messages.error(request, "Create your owner profile first.")
        return redirect("owner_profile_manage")

    vehicle = get_object_or_404(Vehicle.objects.prefetch_related("images"), id=vehicle_id, owner=owner)
    form = VehicleForm(request.POST or None, request.FILES or None, instance=vehicle)
    if request.method == "POST" and form.is_valid():
        form.save()
        for uploaded in request.FILES.getlist("gallery_images"):
            VehicleImage.objects.create(vehicle=vehicle, image=uploaded)
        messages.success(request, "Vehicle updated successfully.")
        return redirect("vehicle_manage")

    return render(
        request,
        "management/vehicle_edit.html",
        {"form": form, "vehicle": vehicle, "owner": owner},
    )


@login_required
@require_POST
def vehicle_delete(request, vehicle_id):
    owner = OwnerProfile.objects.filter(user=request.user).first()
    if not owner:
        messages.error(request, "Create your owner profile first.")
        return redirect("owner_profile_manage")

    vehicle = get_object_or_404(Vehicle, id=vehicle_id, owner=owner)
    vehicle.delete()
    messages.success(request, "Vehicle deleted.")
    return redirect("vehicle_manage")


@login_required
@require_POST
def vehicle_image_delete(request, image_id):
    owner = OwnerProfile.objects.filter(user=request.user).first()
    if not owner:
        messages.error(request, "Create your owner profile first.")
        return redirect("owner_profile_manage")

    image = get_object_or_404(VehicleImage.objects.select_related("vehicle"), id=image_id, vehicle__owner=owner)
    vehicle_id = image.vehicle_id
    image.delete()
    messages.success(request, "Vehicle image removed.")
    return redirect("vehicle_edit", vehicle_id=vehicle_id)


@login_required
def booking_manage(request):
    owner = OwnerProfile.objects.filter(user=request.user).first()
    if not owner:
        messages.error(request, "Create your owner profile first.")
        return redirect("owner_profile_manage")
    bookings = owner.bookings.select_related("vehicle").order_by("-created_at")
    return render(
        request,
        "management/booking_manage.html",
        {"bookings": bookings, "owner": owner},
    )


@login_required
def expense_manage(request):
    owner = OwnerProfile.objects.filter(user=request.user).first()
    if not owner:
        messages.error(request, "Create your owner profile first.")
        return redirect("owner_profile_manage")
    form = ExpenseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        expense = form.save(commit=False)
        expense.owner = owner
        expense.save()
        messages.success(request, "Expense added successfully.")
        return redirect("expense_manage")

    expenses = owner.expenses.all()
    return render(
        request,
        "management/expense_manage.html",
        {
            "form": form,
            "expenses": expenses,
            "owner": owner,
            "total_revenue": owner.total_revenue,
            "total_expenses": owner.total_expenses,
            "total_profit": owner.total_profit,
        },
    )


@require_GET
def vehicle_list(request):
    vehicles = Vehicle.objects.select_related("owner").prefetch_related("images").filter(
        is_verified=True,
        owner__is_verified=True,
        owner__user__is_active=True,
    )
    data = [
        {
            "id": vehicle.id,
            "category": vehicle.category,
            "name": vehicle.name,
            "brand": vehicle.brand,
            "model_year": vehicle.model_year,
            "registration_number": vehicle.registration_number,
            "rent_per_day": float(vehicle.rent_per_day),
            "is_available": vehicle.is_available,
            "owner": vehicle.owner.business_name,
            "photo_url": vehicle.photo_url,
            "photo": vehicle.photo.url if vehicle.photo else "",
            "gallery_images": [img.image.url for img in vehicle.images.all()],
            "owner_photo_url": vehicle.owner.profile_photo_url,
            "owner_photo": vehicle.owner.profile_photo.url if vehicle.owner.profile_photo else "",
            "display_image_url": _vehicle_image_url(vehicle),
        }
        for vehicle in vehicles
    ]
    return JsonResponse({"results": data})


@require_GET
def booking_list(request):
    bookings = Booking.objects.select_related("vehicle", "owner").all()
    data = [
        {
            "id": booking.id,
            "customer_name": booking.customer_name,
            "customer_phone": booking.customer_phone,
            "customer_email": booking.customer_email,
            "customer_address": booking.customer_address,
            "customer_lpu_id": booking.customer_lpu_id,
            "customer_license_number": booking.customer_license_number,
            "customer_age": booking.customer_age,
            "driving_license_doc": booking.driving_license_doc.url if booking.driving_license_doc else "",
            "student_id_doc": booking.student_id_doc.url if booking.student_id_doc else "",
            "vehicle": str(booking.vehicle),
            "vehicle_image_url": _vehicle_image_url(booking.vehicle),
            "owner": booking.owner.business_name,
            "start_date": booking.start_date.isoformat(),
            "end_date": booking.end_date.isoformat(),
            "start_time": booking.start_time.strftime("%H:%M") if booking.start_time else "",
            "end_time": booking.end_time.strftime("%H:%M") if booking.end_time else "",
            "rental_unit": booking.rental_unit,
            "rent_per_day": float(booking.vehicle.rent_per_day),
            "duration_days": booking.duration_days,
            "duration_hours": booking.duration_hours,
            "total_price": float(booking.total_price),
            "remaining_amount": float(booking.remaining_amount),
            "status": booking.status,
        }
        for booking in bookings
    ]
    return JsonResponse({"results": data})


def _parse_money(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount >= 0 else None


def _parse_iso_date(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _parse_iso_time(value):
    try:
        return datetime.strptime(str(value), "%H:%M").time()
    except (TypeError, ValueError):
        return None


def _decode_data_url_file(data_url, prefix):
    if not data_url or not isinstance(data_url, str) or ";base64," not in data_url:
        return None

    header, encoded = data_url.split(";base64,", 1)
    mime = header.split(":", 1)[-1].lower()
    extension = "bin"
    if mime in {"image/jpeg", "image/jpg"}:
        extension = "jpg"
    elif mime == "image/png":
        extension = "png"
    elif mime == "application/pdf":
        extension = "pdf"

    try:
        decoded = base64.b64decode(encoded)
    except (ValueError, TypeError):
        return None

    filename = f"{prefix}_{uuid.uuid4().hex[:12]}.{extension}"
    return ContentFile(decoded, name=filename)


@csrf_exempt
@require_POST
def otp_send(request):
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON body.")

    purpose = (payload.get("purpose") or "").strip().lower()
    channel = (payload.get("channel") or "").strip().lower()
    target = (payload.get("target") or "").strip()

    if not purpose or channel not in {"email", "phone"} or not target:
        return HttpResponseBadRequest("purpose, channel(email/phone) and target are required.")

    if channel == "phone":
        target = _normalize_indian_phone(target)
        if not target:
            return HttpResponseBadRequest("Enter a valid Indian mobile number.")

    otp_id, code = _create_otp(request, purpose, channel, target)

    try:
        if channel == "email":
            sent, message = _send_email_otp(target, code)
        else:
            sent, message = _send_phone_otp(target, code)
    except Exception:
        return HttpResponseBadRequest("OTP delivery failed due to service error.")

    if not sent:
        return HttpResponseBadRequest(message)

    response = {"otp_id": otp_id, "message": message}
    if settings.DEBUG or "Demo mode" in message or not settings.EMAIL_HOST or not settings.TWILIO_ACCOUNT_SID:
        response["debug_otp"] = code
    return JsonResponse(response)


@csrf_exempt
@require_POST
def otp_verify(request):
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON body.")

    otp_id = (payload.get("otp_id") or "").strip()
    otp_code = (payload.get("otp_code") or "").strip()

    if not otp_id or not otp_code:
        return HttpResponseBadRequest("otp_id and otp_code are required.")

    store = _otp_session_store(request)
    record = store.get(otp_id)
    if not record:
        return HttpResponseBadRequest("OTP not found.")

    if int(time.time()) > int(record.get("expires_at") or 0):
        return HttpResponseBadRequest("OTP has expired.")

    if str(record.get("code")) != otp_code:
        return HttpResponseBadRequest("Invalid OTP.")

    record["verified"] = True
    store[otp_id] = record
    request.session["otp_store"] = store
    _mark_otp_verified(request, record["purpose"], record["channel"], record["target"])

    return JsonResponse({"verified": True, "message": "OTP verified."})


@csrf_exempt
@require_POST
def add_expense(request):
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON body.")

    owner_id = payload.get("owner_id")
    title = payload.get("title")
    amount = _parse_money(payload.get("amount"))

    if not owner_id or not title or amount is None:
        return HttpResponseBadRequest("owner_id, title and a valid amount are required.")

    owner = get_object_or_404(OwnerProfile, id=owner_id)
    expense = Expense.objects.create(
        owner=owner,
        title=title,
        amount=amount,
        notes=payload.get("notes", ""),
    )

    return JsonResponse(
        {
            "id": expense.id,
            "owner": owner.business_name,
            "title": expense.title,
            "amount": float(expense.amount),
            "spent_on": expense.spent_on.isoformat(),
        },
        status=201,
    )


@csrf_exempt
@require_POST
def create_booking(request):
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON body.")

    vehicle_id = payload.get("vehicle_id")
    customer_name = (payload.get("customer_name") or "").strip()
    customer_phone = (payload.get("customer_phone") or "").strip()
    customer_email = (payload.get("customer_email") or "").strip()
    customer_address = (payload.get("customer_address") or "").strip()
    customer_lpu_id = (payload.get("customer_lpu_id") or "").strip()
    customer_license_number = (payload.get("customer_license_number") or "").strip()
    customer_age = payload.get("customer_age")
    rental_unit = (payload.get("rental_unit") or Booking.RentalUnit.DAY).strip().lower()
    start_date = payload.get("start_date")
    end_date = payload.get("end_date")
    start_time = payload.get("start_time")
    end_time = payload.get("end_time")
    total_price = _parse_money(payload.get("total_price"))
    driving_license_doc = _decode_data_url_file(payload.get("driving_license_doc"), "license")
    student_id_doc = _decode_data_url_file(payload.get("student_id_doc"), "student_id")

    if isinstance(customer_age, str):
        customer_age = customer_age.strip()
    if customer_age in ("", None):
        customer_age = None
    else:
        try:
            customer_age = int(customer_age)
        except (TypeError, ValueError):
            return HttpResponseBadRequest("customer_age must be a valid number.")

    if (
        not vehicle_id
        or not customer_name
        or not customer_phone
        or not customer_email
        or not customer_address
        or not customer_lpu_id
        or not customer_license_number
        or customer_age is None
        or not start_date
        or not end_date
        or driving_license_doc is None
        or student_id_doc is None
    ):
        return HttpResponseBadRequest("Complete profile and both documents are required before booking.")

    if rental_unit not in {Booking.RentalUnit.DAY, Booking.RentalUnit.HOUR}:
        return HttpResponseBadRequest("Invalid rental_unit. Use 'day' or 'hour'.")

    parsed_start_date = _parse_iso_date(start_date)
    parsed_end_date = _parse_iso_date(end_date)
    if not parsed_start_date or not parsed_end_date:
        return HttpResponseBadRequest("start_date and end_date must be valid dates (YYYY-MM-DD).")
    if parsed_end_date < parsed_start_date:
        return HttpResponseBadRequest("end_date must be same or after start_date.")

    parsed_start_time = None
    parsed_end_time = None

    vehicle = get_object_or_404(
        Vehicle.objects.select_related("owner"),
        id=vehicle_id,
        is_verified=True,
        owner__is_verified=True,
        owner__user__is_active=True,
    )

    if not vehicle.is_available:
        return HttpResponseBadRequest("Vehicle is not available.")

    if rental_unit == Booking.RentalUnit.DAY:
        total_days = (parsed_end_date - parsed_start_date).days
        if total_days <= 0:
            return HttpResponseBadRequest("For daily booking, end_date must be after start_date.")
        computed_total = Decimal(total_days) * vehicle.rent_per_day
    else:
        parsed_start_time = _parse_iso_time(start_time)
        parsed_end_time = _parse_iso_time(end_time)
        if not parsed_start_time or not parsed_end_time:
            return HttpResponseBadRequest("For hourly booking, start_time and end_time are required (HH:MM).")
        if parsed_start_date != parsed_end_date:
            return HttpResponseBadRequest("Hourly booking currently supports same-day booking only.")

        start_dt = datetime.combine(parsed_start_date, parsed_start_time)
        end_dt = datetime.combine(parsed_end_date, parsed_end_time)
        if end_dt <= start_dt:
            return HttpResponseBadRequest("For hourly booking, end_time must be after start_time.")

        total_hours = math.ceil((end_dt - start_dt).total_seconds() / 3600)
        hourly_rate = (vehicle.rent_per_day / Decimal("24")).quantize(Decimal("0.01"))
        computed_total = Decimal(total_hours) * hourly_rate

    if total_price is not None and abs(total_price - computed_total) > Decimal("0.5"):
        return HttpResponseBadRequest("Submitted total does not match calculated booking total.")

    booking = Booking.objects.create(
        customer_name=customer_name,
        customer_phone=customer_phone,
        customer_email=customer_email,
        customer_address=customer_address,
        customer_lpu_id=customer_lpu_id,
        customer_license_number=customer_license_number,
        customer_age=customer_age,
        owner=vehicle.owner,
        vehicle=vehicle,
        rental_unit=rental_unit,
        start_date=parsed_start_date,
        end_date=parsed_end_date,
        start_time=parsed_start_time,
        end_time=parsed_end_time,
        total_price=computed_total,
        status=Booking.Status.PENDING,
        driving_license_doc=driving_license_doc,
        student_id_doc=student_id_doc,
    )

    return JsonResponse(
        {
            "id": booking.id,
            "status": booking.status,
            "vehicle": f"{vehicle.brand} {vehicle.name}",
        },
        status=201,
    )
