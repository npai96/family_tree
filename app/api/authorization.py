"""Server-owned circle permissions shared by API routes and field redaction.

Unknown roles and actions deny access. A browser control is only a hint; these
rules are applied after the API resolves the authenticated user and membership.
"""

from __future__ import annotations

from typing import Literal


CircleAction = Literal[
    "view_circle",
    "edit_circle",
    "edit_person",
    "manage_members",
    "manage_invitations",
    "view_invitations",
    "view_medical_notes",
    "access_media",
    "upload_media",
    "use_realtime",
]

ALL_MEMBERS = frozenset({"owner", "editor", "viewer"})
EDITORS = frozenset({"owner", "editor"})
OWNERS = frozenset({"owner"})

ACTION_ROLES: dict[CircleAction, frozenset[str]] = {
    "view_circle": ALL_MEMBERS,
    "edit_circle": EDITORS,
    "edit_person": EDITORS,
    "manage_members": OWNERS,
    "manage_invitations": OWNERS,
    "view_invitations": EDITORS,
    "view_medical_notes": EDITORS,
    "access_media": ALL_MEMBERS,
    "upload_media": EDITORS,
    "use_realtime": ALL_MEMBERS,
}


def role_allows(role: str, action: CircleAction) -> bool:
    """Return False for an unrecognized role or action (fail closed)."""
    return role in ACTION_ROLES.get(action, frozenset())
