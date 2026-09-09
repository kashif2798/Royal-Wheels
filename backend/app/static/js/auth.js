const otpState = {
  customerSignup: {
    email: { otpId: "", target: "", verified: false },
    phone: { otpId: "", target: "", verified: false }
  },
  customerForgot: {
    email: { otpId: "", target: "", verified: false },
    phone: { otpId: "", target: "", verified: false }
  }
};

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  const text = await response.text();
  if (!response.ok) {
    throw new Error(text || "Request failed");
  }
  return text ? JSON.parse(text) : {};
}

function resetOtpFlowState(flow, channel) {
  otpState[flow][channel] = { otpId: "", target: "", verified: false };
}

function normalizeIndianPhone(rawValue) {
  const digits = String(rawValue || "").replace(/\D/g, "");
  let localDigits = digits;
  if (localDigits.startsWith("91")) {
    localDigits = localDigits.slice(2);
  }
  localDigits = localDigits.slice(0, 10);
  return `+91${localDigits}`;
}

function enforceIndianPhonePrefix(inputId) {
  const input = document.getElementById(inputId);
  if (!input) {
    return;
  }

  const applyValue = () => {
    input.value = normalizeIndianPhone(input.value);
  };

  if (!input.value) {
    input.value = "+91";
  } else {
    applyValue();
  }

  input.addEventListener("focus", () => {
    if (!input.value) {
      input.value = "+91";
    }
  });
  input.addEventListener("input", applyValue);
}

async function sendOtp(flow, channel, target, purpose) {
  if (!target) {
    alert(`Please enter ${channel} first.`);
    return;
  }

  const data = await postJson("/api/otp/send/", {
    purpose,
    channel,
    target
  });

  otpState[flow][channel] = {
    otpId: String(data.otp_id || ""),
    target: String(target).trim(),
    verified: false
  };

  if (data.debug_otp) {
    const targetInputId = flow === "customerSignup"
      ? (channel === "email" ? "emailOtp" : "phoneOtp")
      : (channel === "email" ? "resetEmailOtp" : "resetPhoneOtp");
    const otpInput = document.getElementById(targetInputId);
    if (otpInput) {
      otpInput.value = data.debug_otp;
    }
    alert(`Your OTP is: ${data.debug_otp}\n\n(Auto-filled for you in Demo Mode. Click 'Verify' to proceed)`);
  } else {
    alert("OTP sent successfully to your " + channel + ".");
  }
}

async function verifyOtp(flow, channel, target, code) {
  const state = otpState[flow][channel];
  if (!state.otpId || !state.target) {
    alert(`Please send ${channel} OTP first.`);
    return;
  }
  if (String(state.target).trim() !== String(target).trim()) {
    alert(`${channel} value changed. Please resend OTP.`);
    resetOtpFlowState(flow, channel);
    return;
  }
  if (!code) {
    alert(`Please enter ${channel} OTP.`);
    return;
  }

  await postJson("/api/otp/verify/", {
    otp_id: state.otpId,
    otp_code: String(code).trim()
  });

  otpState[flow][channel].verified = true;
  alert(`${channel.toUpperCase()} OTP verified.`);
}

function signup() {
  if (localStorage.getItem("activeRole") === "admin") {
    alert("Admin is currently logged in. Logout from admin first.");
    window.location.href = "/admin-login/";
    return;
  }

  const name = document.getElementById("name")?.value?.trim();
  const email = document.getElementById("email")?.value?.trim();
  const phone = normalizeIndianPhone(document.getElementById("phone")?.value?.trim());
  const age = document.getElementById("age")?.value?.trim();
  const address = document.getElementById("address")?.value?.trim();
  const license = document.getElementById("license")?.value?.trim();
  const lpuId = document.getElementById("lpuId")?.value?.trim();
  const password = document.getElementById("password")?.value;

  if (!name) {
    alert("Please enter your full name");
    return;
  }

  if (!email) {
    alert("Please enter your email address");
    return;
  }

  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (!emailRegex.test(email)) {
    alert("Please enter a valid email address");
    return;
  }

  if (!phone) {
    alert("Please enter your phone number");
    return;
  }

  if (!password || password.length < 6) {
    alert("Please enter a password (minimum 6 characters)");
    return;
  }

  if (
    !otpState.customerSignup.email.verified ||
    String(otpState.customerSignup.email.target).trim().toLowerCase() !== String(email).toLowerCase()
  ) {
    alert("Please verify your email OTP before signup.");
    return;
  }

  if (
    !otpState.customerSignup.phone.verified ||
    String(otpState.customerSignup.phone.target).trim() !== String(phone).trim()
  ) {
    alert("Please verify your phone OTP before signup.");
    return;
  }

  const customers = JSON.parse(localStorage.getItem("customers") || "[]");
  const legacyCustomer = JSON.parse(localStorage.getItem("customer") || "null");
  if (legacyCustomer && !customers.some((c) => c.email === legacyCustomer.email)) {
    customers.push(legacyCustomer);
  }

  const alreadyExists = customers.some(
    (c) =>
      String(c.email || "").toLowerCase() === email.toLowerCase() ||
      (lpuId && String(c.lpuId || "").toLowerCase() === lpuId.toLowerCase())
  );
  if (alreadyExists) {
    alert("An account with this email or LPU ID already exists. Please login instead.");
    return;
  }

  const user = {
    name,
    email,
    phone: phone || "",
    age: age || "",
    address: address || "",
    license: license || "",
    lpuId: lpuId || "",
    password,
    profilePhoto: ""
  };

  try {
    customers.push(user);
    localStorage.setItem("customers", JSON.stringify(customers));
    localStorage.setItem("customer", JSON.stringify(user));
    alert("Signup successful! Please login.");
    window.location.href = "login.html";
  } catch (error) {
    alert("Error saving account. Please try again.");
    console.error("Signup error:", error);
  }
}

function login() {
  if (localStorage.getItem("activeRole") === "admin") {
    alert("Admin is currently logged in. Logout from admin first.");
    window.location.href = "/admin-login/";
    return;
  }

  const email = document.getElementById("loginEmail")?.value?.trim();
  const password = document.getElementById("loginPassword")?.value;

  if (!email) {
    alert("Please enter your email or LPU ID");
    return;
  }

  if (!password) {
    alert("Please enter your password");
    return;
  }

  const customers = JSON.parse(localStorage.getItem("customers") || "[]");
  const legacyCustomer = JSON.parse(localStorage.getItem("customer") || "null");
  if (legacyCustomer && !customers.some((c) => c.email === legacyCustomer.email)) {
    customers.push(legacyCustomer);
    localStorage.setItem("customers", JSON.stringify(customers));
  }

  if (customers.length === 0) {
    alert("No account found. Please signup first.");
    return;
  }

  const normalizedInput = String(email).toLowerCase();
  const matchedUser = customers.find(
    (customer) =>
      (String(customer.email || "").toLowerCase() === normalizedInput ||
        String(customer.lpuId || "").toLowerCase() === normalizedInput) &&
      password === customer.password
  );

  if (matchedUser) {
    localStorage.setItem("loggedCustomer", JSON.stringify(matchedUser));
    localStorage.setItem("activeRole", "customer");
    alert("Login successful!");
    window.location.href = "Home_index.html";
  } else {
    alert("Invalid email/ID or password. Please try again.");
  }
}

function resetCustomerPassword() {
  if (localStorage.getItem("activeRole") === "admin") {
    alert("Admin is currently logged in. Logout from admin first.");
    window.location.href = "/admin-login/";
    return;
  }

  const email = document.getElementById("resetEmail")?.value?.trim();
  const phone = normalizeIndianPhone(document.getElementById("resetPhone")?.value?.trim());
  const password = document.getElementById("resetPassword")?.value;
  const confirmPassword = document.getElementById("resetConfirmPassword")?.value;

  if (!email || !phone) {
    alert("Please enter email and phone number.");
    return;
  }

  if (!password || password.length < 6) {
    alert("New password must be at least 6 characters.");
    return;
  }

  if (password !== confirmPassword) {
    alert("New password and confirm password do not match.");
    return;
  }

  if (
    !otpState.customerForgot.email.verified ||
    String(otpState.customerForgot.email.target).trim().toLowerCase() !== String(email).toLowerCase()
  ) {
    alert("Please verify reset email OTP first.");
    return;
  }

  if (
    !otpState.customerForgot.phone.verified ||
    String(otpState.customerForgot.phone.target).trim() !== String(phone).trim()
  ) {
    alert("Please verify reset phone OTP first.");
    return;
  }

  const customers = JSON.parse(localStorage.getItem("customers") || "[]");
  const legacyCustomer = JSON.parse(localStorage.getItem("customer") || "null");
  if (legacyCustomer && !customers.some((c) => c.email === legacyCustomer.email)) {
    customers.push(legacyCustomer);
  }

  const normalizedEmail = String(email).toLowerCase();
  const userIndex = customers.findIndex(
    (customer) =>
      String(customer.email || "").toLowerCase() === normalizedEmail &&
      String(customer.phone || "").trim() === String(phone).trim()
  );

  if (userIndex === -1) {
    alert("No customer account found with this email and phone number.");
    return;
  }

  customers[userIndex].password = password;
  localStorage.setItem("customers", JSON.stringify(customers));
  localStorage.setItem("customer", JSON.stringify(customers[userIndex]));

  const loggedCustomer = JSON.parse(localStorage.getItem("loggedCustomer") || "null");
  if (loggedCustomer && String(loggedCustomer.email || "").toLowerCase() === normalizedEmail) {
    loggedCustomer.password = password;
    localStorage.setItem("loggedCustomer", JSON.stringify(loggedCustomer));
  }

  alert("Password updated successfully. Please login.");
  window.location.href = "/login.html";
}

document.addEventListener("DOMContentLoaded", () => {
  enforceIndianPhonePrefix("phone");
  enforceIndianPhonePrefix("resetPhone");

  document.getElementById("sendEmailOtpBtn")?.addEventListener("click", async () => {
    try {
      await sendOtp(
        "customerSignup",
        "email",
        document.getElementById("email")?.value?.trim(),
        "customer_signup"
      );
    } catch (error) {
      alert(error.message || "Unable to send email OTP.");
    }
  });

  document.getElementById("verifyEmailOtpBtn")?.addEventListener("click", async () => {
    try {
      await verifyOtp(
        "customerSignup",
        "email",
        document.getElementById("email")?.value?.trim(),
        document.getElementById("emailOtp")?.value?.trim()
      );
    } catch (error) {
      alert(error.message || "Unable to verify email OTP.");
    }
  });

  document.getElementById("sendPhoneOtpBtn")?.addEventListener("click", async () => {
    try {
      await sendOtp(
        "customerSignup",
        "phone",
        normalizeIndianPhone(document.getElementById("phone")?.value?.trim()),
        "customer_signup"
      );
    } catch (error) {
      alert(error.message || "Unable to send phone OTP.");
    }
  });

  document.getElementById("verifyPhoneOtpBtn")?.addEventListener("click", async () => {
    try {
      await verifyOtp(
        "customerSignup",
        "phone",
        normalizeIndianPhone(document.getElementById("phone")?.value?.trim()),
        document.getElementById("phoneOtp")?.value?.trim()
      );
    } catch (error) {
      alert(error.message || "Unable to verify phone OTP.");
    }
  });

  document.getElementById("sendResetEmailOtpBtn")?.addEventListener("click", async () => {
    try {
      await sendOtp(
        "customerForgot",
        "email",
        document.getElementById("resetEmail")?.value?.trim(),
        "customer_forgot"
      );
    } catch (error) {
      alert(error.message || "Unable to send reset email OTP.");
    }
  });

  document.getElementById("verifyResetEmailOtpBtn")?.addEventListener("click", async () => {
    try {
      await verifyOtp(
        "customerForgot",
        "email",
        document.getElementById("resetEmail")?.value?.trim(),
        document.getElementById("resetEmailOtp")?.value?.trim()
      );
    } catch (error) {
      alert(error.message || "Unable to verify reset email OTP.");
    }
  });

  document.getElementById("sendResetPhoneOtpBtn")?.addEventListener("click", async () => {
    try {
      await sendOtp(
        "customerForgot",
        "phone",
        normalizeIndianPhone(document.getElementById("resetPhone")?.value?.trim()),
        "customer_forgot"
      );
    } catch (error) {
      alert(error.message || "Unable to send reset phone OTP.");
    }
  });

  document.getElementById("verifyResetPhoneOtpBtn")?.addEventListener("click", async () => {
    try {
      await verifyOtp(
        "customerForgot",
        "phone",
        normalizeIndianPhone(document.getElementById("resetPhone")?.value?.trim()),
        document.getElementById("resetPhoneOtp")?.value?.trim()
      );
    } catch (error) {
      alert(error.message || "Unable to verify reset phone OTP.");
    }
  });
});
