"""V17.1 Enterprise Authentication Core.

Independent registration/login/JWT-claims/middleware for four roles
(candidate, recruiter, admin, super_admin), refresh-token sessions,
Argon2id password hashing, email verification, forgot/reset password,
and multi-device session management.

Backward compatibility: every V16 endpoint (`/auth/register`,
`/auth/login`, `/auth/recruiter/register`, `/auth/recruiter/login`,
`/auth/verify-email`, `/auth/resend-otp`, `/auth/forgot-password`,
`/auth/reset-password`, `/auth/me`) keeps working with its original
request/response shape — new fields (refresh_token, user, session)
are additive, not replacements. Admin/super_admin accounts are never
created here (see app.api.admin.create_admin_user), matching the
"Admin/Super Admin registration must NOT be public" requirement.
"""
from datetime import datetime, timedelta
import hashlib
import hmac
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.account_lockout import (
    clear_lock_if_expired,
    is_locked,
    progressive_delay_seconds,
    record_failed_login,
    record_successful_login,
    seconds_until_unlocked,
)
from app.core.config import settings
from app.core.otp_security import (
    is_attempts_exhausted,
    record_wrong_attempt,
    resend_cooldown_remaining_seconds,
)
from app.core.password_policy import (
    PasswordStrength,
    record_password_history,
    score_password,
    was_recently_used,
)
from app.core.rate_limit import enforce_rate_limit
from app.core.request_context import Actor, set_actor
from app.core.security import (
    ADMIN_ROLES,
    current_session_id,
    current_user,
    hash_password,
    token_for,
    verify_password,
)
from app.core.security_events import SecurityEvent, record_security_event
from app.core.user_agent import parse_user_agent
from app.core.validators import http_url_validator
from app.core.sessions import (
    list_active_sessions,
    revoke_all_sessions,
    revoke_current_session_from_claims,
    revoke_session_by_id,
    revoke_session_by_refresh_token,
    rotate_refresh_token,
    start_session,
)
from app.db.session import get_db
from app.models.domain import EmailVerification, User
from app.email.service import send_transactional_email

router = APIRouter()

PASSWORD_MIN = settings.password_min_length


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

def _validate_strong_password(value: str) -> str:
    if len(value) < PASSWORD_MIN:
        raise ValueError(f"Password must be at least {PASSWORD_MIN} characters")
    return value


class Register(BaseModel):
    email: EmailStr
    password: str = Field(min_length=PASSWORD_MIN, max_length=128)
    password_confirm: str = Field(min_length=1, max_length=128)
    full_name: str = Field(min_length=2, max_length=160)
    phone: str | None = Field(default=None, min_length=7, max_length=20)

    _check_strength = field_validator("password")(_validate_strong_password)

    @model_validator(mode="after")
    def _passwords_match(self):
        if self.password != self.password_confirm:
            raise ValueError("Password and confirmation do not match")
        return self


class RecruiterRegister(Register):
    company_name: str = Field(min_length=2, max_length=220)
    company_website: str | None = Field(default=None, max_length=500)
    company_email: EmailStr
    _validate_urls = http_url_validator("company_website", assume_https=True)


class Login(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    remember_me: bool = False
    device_id: str | None = Field(default=None, max_length=120)
    device_label: str | None = Field(default=None, max_length=220)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class VerifyOTP(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")


class ResendOTP(BaseModel):
    email: EmailStr


class ResetPassword(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")
    new_password: str = Field(min_length=PASSWORD_MIN, max_length=128)
    new_password_confirm: str = Field(min_length=1, max_length=128)

    _check_strength = field_validator("new_password")(_validate_strong_password)

    @model_validator(mode="after")
    def _passwords_match(self):
        if self.new_password != self.new_password_confirm:
            raise ValueError("Password and confirmation do not match")
        return self


class PasswordStrengthRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash(code: str) -> str:
    """V25.6: keyed hash (HMAC-SHA256 with the server secret). A bare SHA-256 of a 6-digit
    code can be reversed with a million-entry lookup by anyone who obtains the table;
    with a server-side key that requires the application secret as well. Codes issued
    before an upgrade stop verifying (they live at most a few minutes) - users request a
    new one."""
    return hmac.new(settings.jwt_secret.encode(), b"otp:" + code.encode(), hashlib.sha256).hexdigest()


def _issue(db: Session, user: User, purpose: str = "verify_email") -> None:
    code = f"{secrets.randbelow(1000000):06d}"
    rows = db.scalars(
        select(EmailVerification).where(
            EmailVerification.user_id == user.id,
            EmailVerification.purpose == purpose,
            EmailVerification.consumed == False,  # noqa: E712
        )
    ).all()
    for old in rows:
        old.consumed = True
    db.add(
        EmailVerification(
            user_id=user.id,
            code_hash=_hash(code),
            purpose=purpose,
            expires_at=datetime.utcnow() + timedelta(minutes=settings.email_otp_minutes),
        )
    )
    db.commit()
    # V23.2 — routed through the centralized template engine
    # (app.email.service.send_transactional_email) instead of calling
    # send_otp directly, so this OTP email is templated, tracked (an
    # EmailMessage/EmailDeliveryAttempt row), and — the important
    # part — a delivery failure can never turn a successful
    # register/resend-code call into a 500: send_transactional_email
    # never raises. The OTP itself (generation/hashing/expiry/single-
    # use) above is completely unchanged. The raw `code` is passed
    # only as an in-memory render variable — never written to
    # EmailMessage.variables_json (persisted_variables omits it
    # entirely), so it never lands at rest outside EmailVerification's
    # own already-hashed `code_hash` column.
    template_key = "EMAIL_VERIFICATION" if purpose == "verify_email" else "PASSWORD_RESET"
    send_transactional_email(
        db,
        user_id=user.id,
        recipient=user.email,
        template_key=template_key,
        render_variables={"user_name": user.full_name or "there", "otp_code": code},
        persisted_variables={"purpose": purpose},
    )


_DUMMY_PASSWORD_HASH: str | None = None


def _burn_password_verification(password: str) -> None:
    global _DUMMY_PASSWORD_HASH
    if _DUMMY_PASSWORD_HASH is None:
        _DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(24))
    try:
        verify_password(password, _DUMMY_PASSWORD_HASH)
    except Exception:  # pragma: no cover - timing padding must never break login
        pass


def _user_profile(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "phone": user.phone,
        "email_verified": user.email_verified,
        "recruiter_status": user.recruiter_status,
        "company_name": user.company_name,
        "company_website": user.company_website,
        "company_email": user.company_email,
    }


def _check_duplicates(db: Session, email: str, phone: str | None) -> None:
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Email already registered")
    if phone:
        if db.scalar(select(User).where(User.phone == phone)):
            raise HTTPException(409, "Phone number already registered")


def _enforce_registration_enabled(db: Session, *, recruiter: bool) -> None:
    """403 if the relevant registration switch is off.

    Uses ``get_setting_safe``, so a transient failure reading the
    setting leaves registration OPEN rather than closed — the setting
    defaults to enabled, and an infrastructure blip must not silently
    stop signups.
    """
    from app.core.platform_settings import get_setting_safe

    key = "recruiter_registration_enabled" if recruiter else "registration_enabled"
    if not get_setting_safe(db, key, True):
        raise HTTPException(
            403,
            "Recruiter registration is currently closed." if recruiter else "Registration is currently closed.",
        )


def _register(payload: Register, request: Request, db: Session, recruiter: bool = False):
    enforce_rate_limit(request, bucket="register")
    # V25.2 — platform settings can close registration (spec section
    # 19). Checked here, in the one function both the candidate and
    # recruiter registration routes already funnel through, so neither
    # can be left ungated. Existing accounts are unaffected: this
    # blocks account *creation* only, never login.
    _enforce_registration_enabled(db, recruiter=recruiter)
    email = str(payload.email).strip().lower()
    phone = payload.phone.strip() if payload.phone else None
    _check_duplicates(db, email, phone)

    # Critical RBAC invariant: recruiter registrations are recruiter-role
    # accounts from creation, but remain unusable until email + admin approval.
    # Admin/super_admin roles are never assignable through this endpoint.
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name.strip(),
        role="recruiter" if recruiter else "candidate",
        active=True,
        email_verified=settings.auto_verify_email_in_tests,
        recruiter_status="pending" if recruiter else None,
        phone=phone,
    )
    if recruiter:
        rp = payload  # RecruiterRegister
        user.company_name = rp.company_name.strip()
        user.company_website = (rp.company_website or "").strip() or None
        user.company_email = str(rp.company_email).strip().lower()
    db.add(user)
    db.commit()
    db.refresh(user)
    record_password_history(db, user.id, user.password_hash)
    db.commit()
    _issue(db, user)
    set_actor(Actor(actor_type="user", actor_id=str(user.id), label=user.email))
    log_audit(db, action="register_recruiter" if recruiter else "register_candidate",
              entity_type="user", entity_id=str(user.id))
    db.commit()
    return {"verification_required": True, "email": email, "message": "Verification code sent to your email"}


@router.post("/register", status_code=201)
def register(payload: Register, request: Request, db: Session = Depends(get_db)):
    """Candidate registration. Alias: POST /auth/candidate/register."""
    return _register(payload, request, db, False)


@router.post("/candidate/register", status_code=201)
def candidate_register(payload: Register, request: Request, db: Session = Depends(get_db)):
    return _register(payload, request, db, False)


@router.post("/recruiter/register", status_code=201)
def recruiter_register(payload: RecruiterRegister, request: Request, db: Session = Depends(get_db)):
    return _register(payload, request, db, True)


@router.post("/verify-email")
def verify_email(payload: VerifyOTP, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(request, bucket="verify-email")
    user = db.scalar(select(User).where(User.email == str(payload.email).lower()))
    if not user:
        raise HTTPException(400, "Invalid verification request")
    row = db.scalar(
        select(EmailVerification)
        .where(
            EmailVerification.user_id == user.id,
            EmailVerification.purpose == "verify_email",
            EmailVerification.consumed == False,  # noqa: E712
        )
        .order_by(EmailVerification.id.desc())
    )
    if not row or row.expires_at < datetime.utcnow() or is_attempts_exhausted(row):
        raise HTTPException(400, "Invalid or expired verification code")
    if not secrets.compare_digest(row.code_hash, _hash(payload.code)):
        # V17.2 — count the wrong guess; past otp_max_attempts this
        # code is invalidated outright (see record_wrong_attempt),
        # requiring a fresh /resend-otp rather than allowing unlimited
        # guesses against one still-valid code.
        record_wrong_attempt(db, row)
        record_security_event(db, SecurityEvent.OTP_VERIFY_FAILED, entity_type="user", entity_id=str(user.id))
        db.commit()
        raise HTTPException(400, "Invalid or expired verification code")
    row.consumed = True
    user.email_verified = True
    set_actor(Actor(actor_type="user", actor_id=str(user.id), label=user.email))
    record_security_event(db, SecurityEvent.OTP_VERIFY_SUCCESS, entity_type="user", entity_id=str(user.id))
    db.commit()
    return {"verified": True, "recruiter_status": user.recruiter_status}


@router.post("/resend-otp")
def resend(payload: ResendOTP, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(request, bucket="resend-otp")
    user = db.scalar(select(User).where(User.email == str(payload.email).lower()))
    if user and not user.email_verified:
        # V17.2 — cooldown between resends. Silently skipped rather
        # than surfaced as a distinct error, matching the existing
        # enumeration-safe response below: the caller can't tell "on
        # cooldown" apart from "no such account" from the response
        # alone, same as they already can't tell "unknown email" apart
        # from "already verified".
        if resend_cooldown_remaining_seconds(db, user.id, "verify_email") == 0:
            _issue(db, user, "verify_email")
            record_security_event(db, SecurityEvent.OTP_RESEND, entity_type="user", entity_id=str(user.id))
            db.commit()
    # Enumeration-safe response.
    return {"message": "If the account exists and is unverified, a new code was sent"}


@router.post("/forgot-password")
def forgot_password(payload: ResendOTP, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(request, bucket="forgot-password")
    user = db.scalar(select(User).where(User.email == str(payload.email).lower()))
    if user and user.active and user.email_verified:
        # V25.6: per-ACCOUNT cooldown (the per-IP limiter above does not stop a distributed
        # sender). Without it anyone could flood a victim's inbox with reset emails, and
        # every new request invalidates the victim's still-valid code (_issue consumes
        # older ones). Silent skip keeps the enumeration-safe response identical.
        if resend_cooldown_remaining_seconds(db, user.id, "reset_password", settings.password_reset_cooldown_seconds) == 0:
            _issue(db, user, "reset_password")
    return {"message": "If a verified account exists, a password reset code was sent"}


@router.post("/reset-password")
def reset_password(payload: ResetPassword, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(request, bucket="reset-password")
    user = db.scalar(select(User).where(User.email == str(payload.email).lower()))
    if not user or not user.active:
        raise HTTPException(400, "Invalid or expired reset request")
    row = db.scalar(
        select(EmailVerification)
        .where(
            EmailVerification.user_id == user.id,
            EmailVerification.purpose == "reset_password",
            EmailVerification.consumed == False,  # noqa: E712
        )
        .order_by(EmailVerification.id.desc())
    )
    if not row or row.expires_at < datetime.utcnow() or is_attempts_exhausted(row):
        raise HTTPException(400, "Invalid or expired reset request")
    if not secrets.compare_digest(row.code_hash, _hash(payload.code)):
        record_wrong_attempt(db, row)
        db.commit()
        raise HTTPException(400, "Invalid or expired reset request")
    if was_recently_used(db, user.id, payload.new_password):
        raise HTTPException(400, f"Choose a password you haven't used in your last {settings.password_history_limit} passwords")
    row.consumed = True
    user.password_hash = hash_password(payload.new_password)
    record_password_history(db, user.id, user.password_hash)
    # A password reset invalidates every existing refresh-token session —
    # if the reset was triggered because credentials leaked, this makes
    # sure any session an attacker already opened is killed too.
    revoke_all_sessions(db, user)
    set_actor(Actor(actor_type="user", actor_id=str(user.id), label=user.email))
    record_security_event(db, SecurityEvent.PASSWORD_RESET, entity_type="user", entity_id=str(user.id))
    db.commit()
    return {"reset": True}


@router.post("/password-strength")
def password_strength(payload: PasswordStrengthRequest) -> PasswordStrength:
    """Strength-meter support API — used by registration/reset forms to
    show live feedback. Never itself a hard gate; PASSWORD_MIN is
    enforced by the Register/ResetPassword schemas regardless of score."""
    return score_password(payload.password)


def _login(payload: Login, request: Request, db: Session, roles: set[str]):
    enforce_rate_limit(request, bucket="login")
    email = str(payload.email).lower()
    user = db.scalar(select(User).where(User.email == email))

    # V17.2 — account lockout, checked before password verification so
    # a locked account stops accepting guesses immediately (this is
    # the standard tradeoff: it confirms the email is registered to
    # anyone probing a locked account, in exchange for actually
    # stopping further brute-force attempts against it, which
    # continuing to return a generic "invalid credentials" would not).
    if user:
        now = datetime.utcnow()
        clear_lock_if_expired(user, now)
        if is_locked(user, now):
            remaining = seconds_until_unlocked(user, now)
            record_security_event(db, SecurityEvent.ACCOUNT_LOCKED_LOGIN_ATTEMPT, entity_type="user", entity_id=str(user.id))
            db.commit()
            raise HTTPException(423, f"Account is temporarily locked. Try again in {remaining} seconds.")
        delay = progressive_delay_seconds(user.failed_login_count) if user.last_failed_login_at else 0
        if delay and (now - user.last_failed_login_at).total_seconds() < delay:
            wait = int(delay - (now - user.last_failed_login_at).total_seconds())
            raise HTTPException(429, f"Please wait {wait} seconds before trying again.")

    if user is None:
        # V25.6: burn one Argon2 verification so "unknown email" costs the same as "wrong
        # password" - otherwise response time reveals which emails are registered.
        _burn_password_verification(payload.password)
    if not user or not verify_password(payload.password, user.password_hash) or not user.active:
        # V16 — record failed attempts (by email, not by guessing which
        # user matched) so repeated failures against one account are
        # visible in the audit trail, not just throttled silently.
        # entity_id is the attempted email rather than a user id since
        # a wrong email never resolves to a user row.
        if user:
            record_failed_login(db, user)
        record_security_event(db, SecurityEvent.LOGIN_FAILED, entity_type="user", entity_id=email)
        db.commit()
        raise HTTPException(401, "Invalid credentials")
    if not user.email_verified:
        raise HTTPException(403, "Verify your email before logging in")
    if user.role not in roles:
        if user.role == "recruiter":
            raise HTTPException(403, "Use the recruiter login")
        if user.role in ADMIN_ROLES:
            raise HTTPException(403, "Use the admin login")
        raise HTTPException(403, "Use the candidate login")
    if user.role == "recruiter" and user.recruiter_status != "approved":
        raise HTTPException(403, "Recruiter account is awaiting admin approval")

    record_successful_login(db, user)
    issued = start_session(
        db, user, request,
        device_id=payload.device_id, device_label=payload.device_label,
        remember_me=payload.remember_me,
    )
    set_actor(Actor(actor_type="user", actor_id=str(user.id), label=user.email))
    record_security_event(db, SecurityEvent.LOGIN_SUCCESS, entity_type="user", entity_id=str(user.id))
    db.commit()
    access_token = token_for(user, session_id=issued.session.id)
    return {
        # V16-compatible fields.
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
        # V17.1 additions.
        "refresh_token": issued.refresh_token,
        "user": _user_profile(user),
        "session": {"id": issued.session.id, "device_id": issued.session.device_id},
    }


@router.post("/login")
def login(payload: Login, request: Request, db: Session = Depends(get_db)):
    """Legacy candidate login, kept for backward compatibility.
    Equivalent to POST /auth/candidate/login."""
    return _login(payload, request, db, {"candidate"})


@router.post("/candidate/login")
def candidate_login(payload: Login, request: Request, db: Session = Depends(get_db)):
    return _login(payload, request, db, {"candidate"})


@router.post("/recruiter/login")
def recruiter_login(payload: Login, request: Request, db: Session = Depends(get_db)):
    return _login(payload, request, db, {"recruiter"})


@router.post("/admin/login")
def admin_login(payload: Login, request: Request, db: Session = Depends(get_db)):
    """Admin/super_admin login. There is no public admin/super_admin
    registration — accounts are provisioned by an existing admin via
    POST /admin/create-admin-user (see app.api.admin).

    V17.2 — checked against its own, stricter rate-limit budget
    (``admin_login_rate_limit_*``) before falling into the shared
    ``_login`` flow (which still applies the general "login" bucket
    too) — admin credentials are a higher-value target, so a tighter
    per-IP budget on top of account lockout is worth the extra check.
    """
    enforce_rate_limit(
        request, bucket="admin-login",
        limit=settings.admin_login_rate_limit_attempts,
        window=settings.admin_login_rate_limit_window_seconds,
    )
    return _login(payload, request, db, ADMIN_ROLES)


@router.post("/refresh")
def refresh(payload: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    """Exchange a refresh token for a new access token + rotated
    refresh token. See app.core.sessions for rotation/reuse-detection
    semantics."""
    enforce_rate_limit(request, bucket="refresh")
    user, issued = rotate_refresh_token(db, payload.refresh_token)
    db.commit()
    access_token = token_for(user, session_id=issued.session.id)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
        "refresh_token": issued.refresh_token,
        "user": _user_profile(user),
    }


@router.post("/logout")
def logout(
    payload: LogoutRequest,
    user: User = Depends(current_user),
    session_id: int | None = Depends(current_session_id),
    db: Session = Depends(get_db),
):
    """Logout of the current device/session only.

    V25.6: also revokes the session identified by the caller's own access token (``sid``),
    so logout works even when the client does not send its refresh token, and - together
    with the per-request session check in app.core.security - the access token stops
    working immediately."""
    revoke_current_session_from_claims(db, user, session_id)
    if payload.refresh_token:
        revoke_session_by_refresh_token(db, payload.refresh_token, user)
    record_security_event(db, SecurityEvent.LOGOUT, entity_type="user", entity_id=str(user.id))
    db.commit()
    return {"logged_out": True}


@router.post("/logout-all")
def logout_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Logout of every device/session for the current user."""
    count = revoke_all_sessions(db, user)
    record_security_event(db, SecurityEvent.LOGOUT_ALL, entity_type="user", entity_id=str(user.id), detail=f"sessions_revoked={count}")
    db.commit()
    return {"logged_out": True, "sessions_revoked": count}


@router.get("/sessions")
def sessions(
    user: User = Depends(current_user),
    session_id: int | None = Depends(current_session_id),
    db: Session = Depends(get_db),
):
    """List this user's active (non-revoked) sessions/devices.

    V17.3: added device/browser/os (parsed from the stored user_agent,
    nothing new persisted), is_current (compares each session's id to
    the current request's own ``sid`` JWT claim), and country — always
    null: no IP-geolocation lookup is performed (no such service is
    configured or reachable from this codebase), and returning a
    fabricated or silently-omitted value would be worse than an
    honest null. All pre-existing fields are unchanged.
    """
    result = []
    for s in list_active_sessions(db, user):
        ua = parse_user_agent(s.user_agent)
        result.append(
            {
                "id": s.id,
                "device_id": s.device_id,
                "device_label": s.device_label,
                "ip_address": s.ip_address,
                "user_agent": s.user_agent,
                "browser": ua["browser"],
                "os": ua["os"],
                "device": ua["device"],
                "country": None,
                "remember_me": s.remember_me,
                "created_at": s.created_at,
                "last_seen_at": s.last_seen_at,
                "is_current": session_id is not None and s.id == session_id,
            }
        )
    return result


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Logout a specific device (e.g. "log out my old phone")."""
    ok = revoke_session_by_id(db, user, session_id)
    if not ok:
        raise HTTPException(404, "Session not found")
    record_security_event(db, SecurityEvent.SESSION_REVOKED, entity_type="user_session", entity_id=str(session_id))
    db.commit()
    return {"revoked": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return _user_profile(user)
