# Focused workspace implementation

October 31, 2026. Approved after review of the October 30 prototype.

## Problem and decision

The five-space shell relocated legacy panels but retained duplicate actions and mixed unrelated tasks. This release makes the tree the default home, narrows everyday navigation to Tree, People, and Places & time, and separates Family access from personal account actions.

| Decision | Reason and audit traps | Implementation |
| --- | --- | --- |
| Tree is home; `#home` remains an alias | Ambiguous home, redundancy | No competing dashboard or repeated navigation cards |
| One Add person action on Tree/People | Distraction, redundancy | Removed global Add and relationship-panel duplicate |
| Separate account and family access | Poor grouping | One family picker; account menu owns code and sign-out; Family access owns invitations, members, ownership, history |
| Plain read view, then edit | Information overload | Two profile tabs: Story and Photos; conversation, revisions and authorized health notes are secondary sections |
| Accurate birthplace label | Incorrect information | `birth_place` no longer displayed as Home |
| Guard unsaved edits; report save result locally | Data loss, feedback failure | Draft survives page navigation; person/circle change and close warn; failed saves retain input; saving disables fields |
| Automatically load bounded initial tree | Unnecessary steps | Existing authenticated graph request, existing cancellation and circle checks; advanced options retain Apply view for explicit changes/retry |
| Optional story journey | Forced sequence, unnecessary steps | Existing guided questions remain, with Skip optional details after name; duplicate check and partial-link recovery remain |
| Recorded places first, maps/context secondary | Poor grouping, overload | Existing place list, form, exports and timeline remain available without presenting every control at once |
| Restrained typography and mobile navigation | Inconsistent appearance, physical challenge | Warm neutral/sage palette, compact headers, three-item mobile navigation, mobile person selector |

## Architecture and privacy

The React workspace composes existing panels and handlers. Python authorization, session cookies, CSRF, approved tester admission, private media tickets, database schema and storage configuration are unchanged. UI hiding is not authorization. The browser still depends on the API to reject forbidden operations and redact medical notes.

Form and panel state remain in memory. No new local-storage persistence for family stories or medical notes was added. Account/circle keys still remount private workspace state. Existing sign-out clears private state rather than retaining drafts after logout.

## Verification

- JavaScript unit checks: 19 passed.
- Python/API checks: 102 passed; 12 opt-in PostgreSQL checks skipped. This change introduces no schema/backend changes; skipped tests are not a claim of hosted PostgreSQL verification.
- Authenticated disposable local API browser checks: owner profile save; failed PATCH preserves draft and displays error; cancelling a person change retains draft; navigation/back retains draft; lazy media; automatically loaded graph and Fit; places; invitation form; optional-short-path person save/reveal; mobile overflow; logout removes private UI; separate real viewer cannot edit or see medical-note text.
- Screenshots captured at desktop and 390px mobile widths. Data is fictional. These are implementation checks, not evidence of user comprehension or improved task completion.

## Differences from the proposal and remaining research

- The production D3 graph and media/timeline components remain in use; the prototype's fixed sample graph and photo placeholders were not copied into production.
- Existing guided entry remains with an optional skip rather than being replaced wholesale by the prototype's single form. This preserves duplicate detection and partial relationship-save recovery.
- Advanced map/export and context tools remain in disclosures using existing data. No geocoder, inferred migration path, or new historical source was introduced.
- Member names use only identities already available to the authorized app; hosted IDs remain a fallback. This release does not broaden the user directory API.
- Some secondary forms retain global status feedback. Profile saving now has local feedback. Continue testing other mutation failures and contextual guidance with users.
- The audit's 27 rows are a continuing evaluation framework, not a declaration that every possible trap has been eliminated. Larger-family layouts, assistive technology, hosted Google owner/viewer acceptance and task-based user observation remain useful follow-up checks.

## Portfolio narrative

Show the contrast between organizing controls into tabs and organizing the interface around tasks. Use a horizontal journey with: previous shell, audit finding, approved proposal, implemented page, reason for the change. Describe reduced visible choices as a design decision. Do not invent task-time, satisfaction or conversion metrics. The personal website is not modified by this application release.
