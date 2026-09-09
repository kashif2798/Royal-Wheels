const adminOtpState = {
  adminSignup: {
    email: { otpId: "", target: "", verified: false },
    phone: { otpId: "", target: "", verified: false }
  },
  adminForgot: {
    email: { otpId: "", target: "", verified: false },
    phone: { otpId: "", target: "", verified: false }
  }
};

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

async function adminPostJson(url, payload) {
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

async function adminSendOtp(flow, channel, target, purpose) {
  if (!target) {
    alert(`Please enter ${channel} first.`);
    return;
  }
  const data = await adminPostJson("/api/otp/send/", { purpose, channel, target });
  adminOtpState[flow][channel] = { otpId: String(data.otp_id || ""), target: String(target).trim(), verified: false };
  if (data.debug_otp) {
    const targetInputId = flow === "adminSignup"
      ? (channel === "email" ? "adminSignupEmailOtp" : "adminSignupPhoneOtp")
      : (channel === "email" ? "adminForgotEmailOtp" : "adminForgotPhoneOtp");
    const otpInput = document.getElementById(targetInputId);
    if (otpInput) {
      otpInput.value = data.debug_otp;
    }
    alert(`Your OTP is: ${data.debug_otp}\n\n(Auto-filled for you in Demo Mode. Click 'Verify' to proceed)`);
  } else {
    alert("OTP sent to your " + channel + ".");
  }
}

async function adminVerifyOtp(flow, channel, target, code) {
  const state = adminOtpState[flow][channel];
  if (!state.otpId || !state.target) {
    alert(`Please send ${channel} OTP first.`);
    return;
  }
  if (String(state.target).trim() !== String(target).trim()) {
    alert(`${channel} value changed. Resend OTP.`);
    adminOtpState[flow][channel] = { otpId: "", target: "", verified: false };
    return;
  }
  if (!code) {
    alert(`Enter ${channel} OTP.`);
    return;
  }

  await adminPostJson("/api/otp/verify/", { otp_id: state.otpId, otp_code: String(code).trim() });
  adminOtpState[flow][channel].verified = true;
  alert(`${channel.toUpperCase()} OTP verified.`);
}

document.addEventListener("DOMContentLoaded", () => {
  enforceIndianPhonePrefix("phone");
  enforceIndianPhonePrefix("adminForgotPhone");

  document.getElementById("sendAdminSignupEmailOtp")?.addEventListener("click", async () => {
    try {
      await adminSendOtp("adminSignup", "email", document.getElementById("email")?.value?.trim(), "admin_signup");
    } catch (error) {
      alert(error.message || "Unable to send email OTP.");
    }
  });

  document.getElementById("verifyAdminSignupEmailOtp")?.addEventListener("click", async () => {
    try {
      await adminVerifyOtp(
        "adminSignup",
        "email",
        document.getElementById("email")?.value?.trim(),
        document.getElementById("adminSignupEmailOtp")?.value?.trim()
      );
    } catch (error) {
      alert(error.message || "Unable to verify email OTP.");
    }
  });

  document.getElementById("sendAdminSignupPhoneOtp")?.addEventListener("click", async () => {
    try {
      await adminSendOtp(
        "adminSignup",
        "phone",
        normalizeIndianPhone(document.getElementById("phone")?.value?.trim()),
        "admin_signup"
      );
    } catch (error) {
      alert(error.message || "Unable to send phone OTP.");
    }
  });

  document.getElementById("verifyAdminSignupPhoneOtp")?.addEventListener("click", async () => {
    try {
      await adminVerifyOtp(
        "adminSignup",
        "phone",
        normalizeIndianPhone(document.getElementById("phone")?.value?.trim()),
        document.getElementById("adminSignupPhoneOtp")?.value?.trim()
      );
    } catch (error) {
      alert(error.message || "Unable to verify phone OTP.");
    }
  });

  document.getElementById("sendAdminForgotEmailOtp")?.addEventListener("click", async () => {
    try {
      await adminSendOtp(
        "adminForgot",
        "email",
        document.getElementById("adminForgotEmail")?.value?.trim(),
        "admin_forgot"
      );
    } catch (error) {
      alert(error.message || "Unable to send email OTP.");
    }
  });

  document.getElementById("verifyAdminForgotEmailOtp")?.addEventListener("click", async () => {
    try {
      await adminVerifyOtp(
        "adminForgot",
        "email",
        document.getElementById("adminForgotEmail")?.value?.trim(),
        document.getElementById("adminForgotEmailOtp")?.value?.trim()
      );
    } catch (error) {
      alert(error.message || "Unable to verify email OTP.");
    }
  });

  document.getElementById("sendAdminForgotPhoneOtp")?.addEventListener("click", async () => {
    try {
      await adminSendOtp(
        "adminForgot",
        "phone",
        normalizeIndianPhone(document.getElementById("adminForgotPhone")?.value?.trim()),
        "admin_forgot"
      );
    } catch (error) {
      alert(error.message || "Unable to send phone OTP.");
    }
  });

  document.getElementById("verifyAdminForgotPhoneOtp")?.addEventListener("click", async () => {
    try {
      await adminVerifyOtp(
        "adminForgot",
        "phone",
        normalizeIndianPhone(document.getElementById("adminForgotPhone")?.value?.trim()),
        document.getElementById("adminForgotPhoneOtp")?.value?.trim()
      );
    } catch (error) {
      alert(error.message || "Unable to verify phone OTP.");
    }
  });
});
