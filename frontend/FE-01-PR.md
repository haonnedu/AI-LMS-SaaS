# fix(frontend): cancel stale mock logins and reset mobile menu

Leaving the login preview during a pending sign-in now invalidates that operation.
Late success/error/finally handlers cannot create a session, redirect, or unlock
a newer attempt. Logout invalidates expiry work, and route changes reset the
mobile menu so expiry returns to a scrollable login screen with focus restored.

## Validation

- Frontend lint, typecheck, production build and standalone preparation passed.
- Browser checks covered pending navigation cancellation, retry after error or
  cancellation, replacing sessions before old expiry, expiry with mobile menu
  open, login again with menu closed, logout, reload and keyboard navigation.
- Standalone production login/logout passed; development scenario controls were
  absent and the demo notice remained visible. Cold-reload console warnings/errors
  were empty.
- DOM checks at 375×812 and 1440×900 showed no horizontal overflow.

## Remaining acceptance

Visual signoff remains pending: in-app browser captures render inconsistently
with measured DOM rectangles. Raw captures and geometry are linked from
[the handoff](FE-01.md). Do not mark the mock ready for review until reliable
desktop/mobile/menu images have been checked.

This remains mock auth with React-memory sessions. Real provider integration and
Hao's review are outstanding; FE-01 stays `in_progress`. No dependencies, backend
endpoints, migrations, generated API types or authorization behavior changed.

This file is a local PR draft; no remote PR or deployment has been created.
