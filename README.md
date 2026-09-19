# Royal Wheels

Royal Wheels is a vehicle rental platform built with Django. It connects customers who want to rent cars and bikes with local rental partners, and gives each partner a management console for their fleet, bookings, expenses and revenue.

**Live application:** DEPLOYED_URL_PLACEHOLDER

**Repository:** https://github.com/kashif2798/Royal-Wheels

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Technology Stack](#technology-stack)
- [System Architecture](#system-architecture)
- [Data Model](#data-model)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Application Routes](#application-routes)
- [API Reference](#api-reference)
- [Deployment](#deployment)
- [Project Structure](#project-structure)
- [Security Considerations](#security-considerations)
- [Roadmap](#roadmap)
- [License](#license)

---

## Overview

The platform is a two-sided marketplace. Customers browse a catalogue of verified cars and bikes, filter by category, and submit a booking request with the documents required for a rental. Rental partners register a business account, list their vehicles, and approve or reject incoming bookings from a dedicated dashboard that also tracks expenses and profitability.

Every partner account and every vehicle listing passes through a verification flag before it becomes publicly visible, so the customer-facing catalogue only ever shows approved inventory from active, verified partners.

## Features

### Customer

- Browse verified cars and bikes with images, specifications and daily rates
- Separate catalogue pages for cars, bikes and partner businesses
- Booking form supporting both per-day and per-hour rental units
- Upload of driving licence and student identity documents at booking time
- OTP verification over email or SMS during signup and account recovery
- Booking history page with status, duration and outstanding balance
- Payment page prepared for gateway integration

### Rental Partner

- Business account registration with OTP-verified signup and password reset
- Vehicle management: create, edit, delete listings and manage a gallery of images per vehicle
- Booking queue with approve, reject and completion actions
- Expense logging against the business
- Dashboard summarising revenue, expenses, profit and booking counts, exposed both as a page and as a JSON endpoint

### Administration

- Django admin for user, partner and vehicle records
- Verification workflow controlling public visibility of partners and vehicles
- Management command to seed demonstration partners and inventory

## Technology Stack

| Layer | Technology |
|---|---|
| Framework | Django 6.0.2 |
| Language | Python 3.12 |
| Database | SQLite (development), PostgreSQL via `DATABASE_URL` (production) |
| Templating | Django Templates |
| Frontend | HTML5, CSS3, vanilla JavaScript (no build step) |
| Static files | WhiteNoise with compressed manifest storage |
| Application server | Gunicorn |
| SMS delivery | Twilio |
| Email delivery | SMTP |
| Hosting | Render (primary), Railway or Vercel supported |

## System Architecture

Royal Wheels is a server-rendered Django application with a light JSON layer for the dynamic parts of the interface.

- Page views render Django templates for every screen of the site.
- A small set of JSON endpoints under `/api/` serves the catalogue, booking list, dashboard metrics and OTP flows; the client-side JavaScript consumes these with `fetch`.
- OTP codes are generated server-side, held in the session with a five-minute expiry, and delivered by email or SMS depending on the requested channel. Verified state is recorded per purpose, channel and target, so a verified email cannot be reused for a different flow.
- Uploaded documents and vehicle photographs are stored on the filesystem under `MEDIA_ROOT`; the models also accept external image URLs as an alternative, and the catalogue falls back to bundled placeholder artwork when neither is present.
- Static assets are served by WhiteNoise in production, removing the need for a separate web server in front of the application.

## Data Model

| Model | Purpose |
|---|---|
| `OwnerProfile` | A rental partner. One-to-one with a Django user; holds business name, contact details, licence number and the verification flag. Exposes derived `total_revenue`, `total_expenses` and `total_profit` properties. |
| `Vehicle` | A rentable car or bike belonging to a partner. Stores category, brand, model year, unique registration number, fuel type, seats, transmission, daily rate, availability and verification flag. |
| `VehicleImage` | Additional gallery images for a vehicle. |
| `Booking` | A rental reservation. Captures customer contact details, identity and licence documents, the rental window as dates and optional times, the rental unit, pricing, advance paid and status (`pending`, `confirmed`, `completed`, `cancelled`). Derives duration in days or hours and the remaining balance. |
| `Expense` | A business expense recorded against a partner, used in the profit calculation. |

All models inherit `created_at` and `updated_at` timestamps from a shared abstract base.

## Getting Started

### Prerequisites

- Python 3.12
- pip and virtualenv
- PostgreSQL (optional; SQLite is used by default)

### Installation

```bash
git clone https://github.com/kashif2798/Royal-Wheels.git
cd Royal-Wheels

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### Environment

```bash
cp .env.example .env
```

Set at minimum a `SECRET_KEY`, `DEBUG=True` and `ALLOWED_HOSTS=localhost,127.0.0.1` for local work. A key can be generated with:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### Database and demonstration data

```bash
cd backend
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_partners     # optional: loads demo partners and vehicles
```

### Run

```bash
python manage.py runserver
```

The application is then available at `http://localhost:8000/` and the Django admin at `http://localhost:8000/admin/`.

## Configuration

All configuration is read from environment variables.

| Variable | Description | Default |
|---|---|---|
| `SECRET_KEY` | Django secret key | Development placeholder; must be overridden in production |
| `DEBUG` | Debug mode | `False` |
| `ALLOWED_HOSTS` | Comma-separated host allowlist | `localhost,127.0.0.1,.vercel.app` |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated trusted origins | `https://*.onrender.com,https://*.vercel.app` |
| `DATABASE_URL` | PostgreSQL connection string; SQLite is used when unset | unset |
| `SECURE_SSL_REDIRECT` | Force HTTPS redirects | `False` |
| `SESSION_COOKIE_SECURE` | Send session cookie over HTTPS only | `False` |
| `CSRF_COOKIE_SECURE` | Send CSRF cookie over HTTPS only | `False` |
| `SECURE_HSTS_SECONDS` | HSTS max-age | `0` |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | Apply HSTS to subdomains | `False` |
| `SECURE_HSTS_PRELOAD` | HSTS preload directive | `False` |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` | SMTP settings for email OTP | Empty / `587` / `true` |
| `DEFAULT_FROM_EMAIL` | Sender address for outbound mail | `no-reply@royalwheels.local` |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | Twilio credentials for SMS OTP | Empty |

When email or SMS credentials are absent, the OTP endpoint operates in demonstration mode and returns the generated code in the response so the flow remains testable locally. This behaviour must not be relied upon in production.

## Application Routes

| Route | Description |
|---|---|
| `/` | Home page and vehicle highlights |
| `/Car.html` | Car catalogue |
| `/Bikes.html` | Bike catalogue |
| `/AllPartners.html` | Directory of verified rental partners |
| `/Book_now.html` | Booking form |
| `/payment.html` | Payment screen |
| `/MyBooking.html` | Customer booking history |
| `/profile.html` | Customer profile |
| `/login.html`, `/signup.html`, `/forgot-password.html` | Customer authentication |
| `/admin-login/`, `/admin-signup/`, `/admin-forgot-password/` | Partner authentication |
| `/dashboard/` | Partner dashboard |
| `/management/vehicles/` | Vehicle listing management |
| `/management/vehicles/<id>/edit/` | Edit a vehicle |
| `/management/bookings/` | Booking queue |
| `/management/expenses/` | Expense log |
| `/management/profile/` | Partner business profile |
| `/admin/` | Django administration |

## API Reference

All endpoints return JSON. Request bodies are JSON unless stated otherwise.

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/vehicles/` | Verified vehicles from verified, active partners, including resolved image URLs |
| GET | `/api/bookings/` | Bookings with customer, vehicle, duration and balance details |
| GET | `/api/dashboard/` | Revenue, expense, profit and booking statistics for the signed-in partner (authentication required) |
| POST | `/api/bookings/create/` | Create a booking; accepts customer details, rental window, pricing and base64-encoded document uploads |
| POST | `/api/expenses/add/` | Record an expense against the signed-in partner |
| POST | `/api/otp/send/` | Issue an OTP. Body: `purpose`, `channel` (`email` or `phone`), `target` |
| POST | `/api/otp/verify/` | Verify an OTP. Body: `otp_id`, `otp_code` |

Example:

```bash
curl -X POST http://localhost:8000/api/otp/send/ \
  -H "Content-Type: application/json" \
  -d '{"purpose": "signup", "channel": "email", "target": "user@example.com"}'
```

## Deployment

The repository ships with configuration for three platforms.

### Render (recommended)

`render.yaml` declares a web service and a managed PostgreSQL instance, generates a secret key, and enables the HTTPS and HSTS settings. Connect the repository in Render and the blueprint provisions both services.

Build command:

```
pip install -r requirements.txt && python backend/manage.py migrate --noinput && python backend/manage.py seed_partners && python backend/manage.py collectstatic --noinput
```

Start command:

```
gunicorn backend.wsgi:application --chdir backend --bind 0.0.0.0:$PORT
```

### Railway

Railway detects the Python runtime and the `Procfile` automatically. Set the environment variables listed in [Configuration](#configuration) in the project dashboard.

### Vercel

`vercel.json` and `server.py` provide a serverless WSGI entry point. Because the serverless filesystem is ephemeral, uploaded documents and vehicle photographs will not persist between invocations; Render or Railway is preferred unless media storage is moved to an object store such as Amazon S3.

## Project Structure

```
Royal-Wheels/
├── backend/
│   ├── app/
│   │   ├── models.py                 # Domain models
│   │   ├── views.py                  # Page views and JSON endpoints
│   │   ├── urls.py                   # Application routing
│   │   ├── forms.py                  # Form validation
│   │   ├── admin.py                  # Admin registration
│   │   ├── migrations/               # Schema migrations
│   │   ├── management/commands/      # seed_partners
│   │   ├── templates/                # HTML templates
│   │   └── static/                   # CSS, JavaScript, images
│   ├── backend/
│   │   ├── settings.py               # Configuration
│   │   ├── urls.py                   # Root routing
│   │   ├── wsgi.py                   # WSGI entry point
│   │   └── asgi.py                   # ASGI entry point
│   ├── media/                        # Uploaded documents and photographs
│   └── manage.py
├── server.py                         # Serverless WSGI entry point
├── requirements.txt
├── runtime.txt
├── Procfile
├── render.yaml
├── vercel.json
├── .env.example
├── DEPLOYMENT.md
└── README.md
```

## Security Considerations

Before running the application in production:

- Replace the development `SECRET_KEY` with a generated value supplied through the environment
- Set `DEBUG=False` and restrict `ALLOWED_HOSTS` to the deployed domains
- Enable `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` and HSTS
- Use PostgreSQL rather than SQLite
- Configure real SMTP and Twilio credentials so OTP codes are never returned in API responses
- Move uploaded media to object storage rather than the application filesystem
- Keep `.env` out of version control; only `.env.example` is committed

## Roadmap

- Payment gateway integration (Razorpay, Stripe)
- Customer reviews and partner ratings
- Email and SMS notifications for booking status changes
- Search and filtering improvements on the catalogue
- Extended analytics for partners
- Automated test coverage for booking and OTP flows

## License

This project is released for academic and demonstration purposes. All rights reserved by the author.

## Author

**Kashif Khan**
B.Tech Computer Science, Birla Institute of Technology, Mesra
GitHub: [kashif2798](https://github.com/kashif2798)
