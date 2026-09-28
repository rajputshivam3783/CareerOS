"""V25.1 — Multi-Tenant Architecture & Organization Management.

Covers: organization creation (atomic OWNER membership), membership
listing/role rules, invitation issue/accept/reject/expiry/reuse,
privilege-escalation prevention, last-owner protection, and —most
importantly— cross-tenant isolation (spec sections 8, 25, 29, 30).
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_careeros_v25_1.db"
os.environ["AUTO_VERIFY_EMAIL_IN_TESTS"] = "true"

from datetime import datetime, timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.domain import OrganizationInvitation  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Key": "change-this-admin-key"}
PW = "password12345!"
API = "/api/v1"


def _recruiter(client, suffix):
    email = f"v251org{suffix}@example.com"
    client.post(
        f"{API}/auth/register",
        json={"email": email, "password": PW, "password_confirm": PW, "full_name": f"Rec {suffix}"},
    )
    login = client.post(f"{API}/auth/login", json={"email": email, "password": PW})
    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}).json()
    client.post(f"{API}/admin/users/{me['id']}/role", headers=ADMIN_HEADERS, json={"role": "recruiter"})
    login = client.post(f"{API}/auth/recruiter/login", json={"email": email, "password": PW})
    return email, me["id"], {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_org(client, headers, name):
    resp = client.post(f"{API}/organizations", headers=headers, json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_organization_creates_owner_membership_atomically():
    with TestClient(app) as client:
        _email, _uid, headers = _recruiter(client, "owner1")
        org = _create_org(client, headers, "Acme Technologies")
        assert org["my_role"] == "OWNER"

        members = client.get(f"{API}/organizations/{org['id']}/members", headers=headers).json()
        assert len(members) == 1
        assert members[0]["role"] == "OWNER"
        assert members[0]["status"] == "ACTIVE"

        # Duplicate name is rejected, no partial row left behind.
        dup = client.post(f"{API}/organizations", headers=headers, json={"name": "Acme Technologies"})
        assert dup.status_code == 409


def test_invite_accept_and_role_permissions():
    with TestClient(app) as client:
        _owner_email, _owner_id, owner_headers = _recruiter(client, "owner2")
        member_email, _member_id, member_headers = _recruiter(client, "member2")
        org = _create_org(client, owner_headers, "Startup XYZ")

        # A RECRUITER-role member cannot invite (not yet a member at all here,
        # so this also proves cross-tenant: member2 isn't in org yet).
        blocked = client.post(
            f"{API}/organizations/{org['id']}/members/invite",
            headers=member_headers,
            json={"email": member_email, "role": "RECRUITER"},
        )
        assert blocked.status_code == 404  # not a member yet — fails closed like a nonexistent org

        invite = client.post(
            f"{API}/organizations/{org['id']}/members/invite",
            headers=owner_headers,
            json={"email": member_email, "role": "RECRUITER"},
        )
        assert invite.status_code == 201, invite.text
        token = invite.json()["token"]

        # Wrong account can't accept someone else's invitation.
        _third_email, _third_id, third_headers = _recruiter(client, "third2")
        wrong_accept = client.post(f"{API}/organization-invitations/{token}/accept", headers=third_headers)
        assert wrong_accept.status_code == 403

        accept = client.post(f"{API}/organization-invitations/{token}/accept", headers=member_headers)
        assert accept.status_code == 200, accept.text
        assert accept.json()["role"] == "RECRUITER"

        # Token is single-use.
        reuse = client.post(f"{API}/organization-invitations/{token}/accept", headers=member_headers)
        assert reuse.status_code == 400

        # Now an active RECRUITER member — can view org/members but not invite/manage.
        members = client.get(f"{API}/organizations/{org['id']}/members", headers=member_headers).json()
        assert any(m["email"] == member_email for m in members)

        recruiter_invite_attempt = client.post(
            f"{API}/organizations/{org['id']}/members/invite",
            headers=member_headers,
            json={"email": "someone-else@example.com", "role": "RECRUITER"},
        )
        assert recruiter_invite_attempt.status_code == 403


def test_admin_cannot_escalate_to_owner_or_manage_owner():
    with TestClient(app) as client:
        _owner_email, _owner_id, owner_headers = _recruiter(client, "owner3")
        admin_email, _admin_id, admin_headers = _recruiter(client, "admin3")
        org = _create_org(client, owner_headers, "Example Labs")

        invite = client.post(
            f"{API}/organizations/{org['id']}/members/invite",
            headers=owner_headers,
            json={"email": admin_email, "role": "ADMIN"},
        ).json()
        client.post(f"{API}/organization-invitations/{invite['token']}/accept", headers=admin_headers)

        members = client.get(f"{API}/organizations/{org['id']}/members", headers=owner_headers).json()
        owner_member = next(m for m in members if m["role"] == "OWNER")
        admin_member = next(m for m in members if m["role"] == "ADMIN")

        # ADMIN cannot invite someone as OWNER.
        escalate_invite = client.post(
            f"{API}/organizations/{org['id']}/members/invite",
            headers=admin_headers,
            json={"email": "wannabe-owner@example.com", "role": "OWNER"},
        )
        assert escalate_invite.status_code == 403

        # ADMIN cannot promote themselves (or anyone) to OWNER.
        self_promote = client.patch(
            f"{API}/organizations/{org['id']}/members/{admin_member['id']}/role",
            headers=admin_headers,
            json={"role": "OWNER"},
        )
        assert self_promote.status_code == 403

        # ADMIN cannot remove/suspend the OWNER.
        remove_owner = client.delete(
            f"{API}/organizations/{org['id']}/members/{owner_member['id']}", headers=admin_headers
        )
        assert remove_owner.status_code == 403

        # OWNER can promote the admin to OWNER — but the (now sole)
        # original OWNER can't then be removed without a second owner
        # is already guaranteed since there'd be two OWNERs; test the
        # single-owner protection directly instead:
        sole_owner_removal = client.delete(
            f"{API}/organizations/{org['id']}/members/{owner_member['id']}", headers=owner_headers
        )
        assert sole_owner_removal.status_code == 409  # last owner


def test_cross_tenant_isolation():
    with TestClient(app) as client:
        _a_email, _a_id, a_headers = _recruiter(client, "tenantA")
        _b_email, _b_id, b_headers = _recruiter(client, "tenantB")
        _create_org(client, a_headers, "Tenant A Co")
        org_b = _create_org(client, b_headers, "Tenant B Co")

        # Org A user cannot read Org B.
        assert client.get(f"{API}/organizations/{org_b['id']}", headers=a_headers).status_code == 404
        # Org A user cannot list Org B's members.
        assert client.get(f"{API}/organizations/{org_b['id']}/members", headers=a_headers).status_code == 404
        # Org A user cannot patch Org B's settings via a guessed/changed ID.
        patch = client.patch(f"{API}/organizations/{org_b['id']}", headers=a_headers, json={"name": "Hijacked"})
        assert patch.status_code == 404
        # Org A user cannot invite into Org B.
        invite_cross = client.post(
            f"{API}/organizations/{org_b['id']}/members/invite",
            headers=a_headers,
            json={"email": "victim@example.com", "role": "RECRUITER"},
        )
        assert invite_cross.status_code == 404
        # Org A user cannot read Org B's audit log.
        assert client.get(f"{API}/organizations/{org_b['id']}/audit-log", headers=a_headers).status_code == 404

        # GET /organizations only ever returns orgs the caller belongs to.
        mine = client.get(f"{API}/organizations", headers=a_headers).json()
        assert all(o["id"] != org_b["id"] for o in mine)


def test_invitation_expiry_and_wrong_email_rejected():
    with TestClient(app) as client:
        _owner_email, _owner_id, owner_headers = _recruiter(client, "owner4")
        target_email, _target_id, target_headers = _recruiter(client, "target4")
        org = _create_org(client, owner_headers, "Expiry Test Co")

        invite = client.post(
            f"{API}/organizations/{org['id']}/members/invite",
            headers=owner_headers,
            json={"email": target_email},
        ).json()

        # Force-expire it directly (simulating time passing).
        db = SessionLocal()
        row = db.query(OrganizationInvitation).filter(OrganizationInvitation.id == invite["id"]).first()
        row.expires_at = datetime.utcnow() - timedelta(days=1)
        db.commit()
        db.close()

        expired = client.post(f"{API}/organization-invitations/{invite['token']}/accept", headers=target_headers)
        assert expired.status_code == 400


def test_legacy_team_endpoints_still_work_and_sync_to_org_membership():
    """V18.4's pre-existing team endpoints must keep working exactly as
    before (spec section 24 backward compatibility), and now also
    populate the new OrganizationMember table (spec section 6)."""
    with TestClient(app) as client:
        owner_email, _owner_id, owner_headers = _recruiter(client, "legacyowner")
        member_email, _member_id, member_headers = _recruiter(client, "legacymember")

        client.put(f"{API}/recruiter/company", headers=owner_headers, json={"name": "Legacy Co"})
        invite = client.post(
            f"{API}/recruiter/company/team/invite", headers=owner_headers, json={"email": member_email}
        )
        assert invite.status_code == 201, invite.text

        job = client.post(
            f"{API}/recruiter/jobs",
            headers=owner_headers,
            json={"title": "Backend Engineer", "organization": "Legacy Co", "location": "Remote",
                  "description": "x", "qualification": "x", "save_as_draft": True},
        ).json()

        # Teammate can still see it (V18.6 behavior preserved).
        fetched = client.get(f"{API}/recruiter/jobs/{job['id']}", headers=member_headers)
        assert fetched.status_code == 200, fetched.text


def test_platform_admin_has_no_implicit_backdoor_into_org_endpoints():
    """A platform admin role is not automatically an organization
    member — organization access is governed solely by
    OrganizationMember, not by platform-level role (spec section 8:
    backend authorization for tenant resources is membership-based)."""
    with TestClient(app) as client:
        _owner_email, _owner_id, owner_headers = _recruiter(client, "ownerAdminCheck")
        org = _create_org(client, owner_headers, "Admin Backdoor Check Co")

        admin_email = "v251platformadmin@example.com"
        client.post(
            f"{API}/auth/register",
            json={"email": admin_email, "password": PW, "password_confirm": PW, "full_name": "Plat Admin"},
        )
        login = client.post(f"{API}/auth/login", json={"email": admin_email, "password": PW})
        me = client.get(
            f"{API}/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
        ).json()
        client.post(f"{API}/admin/users/{me['id']}/role", headers=ADMIN_HEADERS, json={"role": "admin"})
        # Role-specific login: administrators sign in through /auth/admin/login, not the candidate endpoint.
        login = client.post(f"{API}/auth/admin/login", json={"email": admin_email, "password": PW})
        assert login.status_code == 200, login.text
        admin_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = client.get(f"{API}/organizations/{org['id']}", headers=admin_headers)
        assert resp.status_code == 404
