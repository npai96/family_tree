# Viraasat UX audit and proposed direction

October 30, 2026. Design review only. No production code or backend changes.

## Scope and evidence

Heuristic evaluation against all 27 traps in the user's supplied UI Tenets & Traps screenshot. Based on the shipped 24ecf34 UI source (`app/web/workspace.js`, `workspace.css`, and composed panels in `app/web/app.js`). The user has directly reported overload and duplication. These are not moderated usability-study results, conversion metrics, or a new security audit. Source-confirmed findings are distinguished from risks that still need observation. Fictional Rao records in the clickable prototype are illustrations, not fetched family data.

The previous redesign rearranged controls without sufficiently redesigning the tasks. The correction is task simplification, not just fewer borders or smaller typography.

## Priority findings

1. **High: redundant actions and competing starting points.** Home renders Add someone both in the hero and header. Tree repeats it in People & Relationships. Circle repeats the sidebar's sign-out and circle selector, while also showing sign-in when already authenticated. Home repeats navigation through a hero, cards, shortcuts, and activity links. Remove the dashboard as a competing home; land on the family tree. One page-level Add person button on Tree and People, never two on the same page. Account actions live only in the account menu.
2. **High: too many unrelated tasks inside Our circle.** Account state, sample exploration, creation, member management, invitations, ownership, change requests, and audit entries are mixed. Split personal Account from Family access. One invite flow for new members; per-member role editing for existing members. Ownership and history remain discoverable under clearly labeled secondary settings.
3. **High: implementation concepts leak into tasks.** Traversal depth, lateral relationships, parent_of, Load Migration GeoJSON, event-type syntax, and ID prefixes force people to learn the internals. Present relationship sentences, generations, and recorded places; retain precise advanced controls behind View options/Map options. Do not silently remove capabilities or change query semantics.
4. **High: context is unreliable.** People/Places select the first person automatically, while selected person and graph root can differ. Separate “Viewing Meera” from “Tree starts with Meera” and preserve each deliberately. Circle changes must clear old private state. Do not invent a recent person if no history exists.
5. **High: a factual label is wrong.** The profile facts label `birth_place` as “Home.” Change it to “Birthplace.” Do not infer residence, life dates, relationships, or migration events from missing data.
6. **High: form feedback and draft loss risks.** A global status message is remote from the form. Person changes reset editing; the add-person dialog can be closed without a draft warning. Display saving/saved/failure beside the relevant action, retain drafts while navigating within the same account/circle, and guard explicit discard. Do not persist sensitive drafts into shared browser storage by default.
7. **Medium: excessive chrome and empty information.** Huge headings, repeated eyebrow/breadcrumb/page-name combinations, the persistent auth-mode chip, decorative profile cover, and per-year “No mapped world events” dominate useful content. Use compact headers, show security information where relevant, and show a single helpful empty state.

## All 27 traps

Severity reflects this interface, not a general importance ranking. “Risk” means the behavior needs direct testing; it is not a measured failure.

| # | Tenet / trap | Evidence or risk in current UI | Proposed correction and verification |
|---|---|---|---|
| 1 | Understandable / Invisible element | Medium, confirmed: owner/editor medical notes are absent from the read view and only reachable through Edit details. | Named Health notes section, collapsed for authorized roles; no note body delivered to viewers. Check discoverability and network redaction separately. |
| 2 | Understandable / Effectively invisible element | Medium, risk: history, membership, and relationship controls are nested below large content and accordions. | Secondary actions grouped under labeled menus; keep selection actions beside the selected person. Test finding history without prompting. |
| 3 | Understandable / Distraction | High, confirmed: decorative Home hero, global Add someone, status chip, repeated navigation. | Tree as home; page-specific actions; avoid promotional copy after sign-in. |
| 4 | Understandable / Uncomprehended element | High, confirmed: traversal/lateral inputs, GeoJSON, raw action names, abbreviated IDs. | Plain-language labels, explain view options, distinguish people in the archive from accounts with access. Names only where the authorized API supplies them; do not expose a global user directory. |
| 5 | Understandable / Inviting dead end | High, confirmed: signed-out nav leads to the same gate; disabled sign-in remains in the authenticated account panel. | Signed-out page has only sign-in/access explanation; show only actions meaningful in the current state. Test expired sessions and no-circle state. |
| 6 | Understandable / Poor grouping | High, confirmed: Our circle combines account, invites, ownership, requests, audit; Places mixes map editing and world-event admin. | Family access contains members and invitations; Account contains sign-out; Places separates reading from adding/editing. |
| 7 | Understandable / Forced syntax | High, confirmed: relationship direction rule, comma-separated relationship/event types, latitude/longitude inputs. | Sentence-based relationship form and labeled choice controls. Coordinates optional in Map options; no new geocoder implied. Preserve endpoint validation. |
| 8 | Understandable / Memory challenge | Medium, confirmed: UUID invitation code must travel between accounts and unrelated panels. | One guided invite dialog explains who supplies the code; Account has a labeled Copy invitation code action and feedback. Keep current invite/accept security flow. |
| 9 | Understandable / Feedback failure | High, risk: form failures appear in page-level workspaceStatus; retained messages can be unrelated to the visible page. | Local save/error state; preserve input after failure; retry where it failed. Test 403, expired session, duplicate and upload failures. |
| 10 | Comfortable / Physical challenge | Medium, risk: long scroll, small controls and multiple nested scrolling regions, especially on mobile. | 44px minimum targets, readable body type, single page scroll except intentional tree pan, bottom navigation and reachable sheets. Test 390px, 200% zoom and keyboard. |
| 11 | Comfortable / Accidental activation | Medium, risk: changing person or closing journey while editing can discard work; adjacent administrative actions. | Guard dirty transitions, separate read/edit modes and dangerous actions. No hover-only commands. |
| 12 | Responsive / Slow or no response | Medium, risk: graph needs manual Render; free host has cold starts; backend speed not measured here. | Initial tree loads automatically with visible loading state; debounce view requests and ignore stale responses. Show cold-start/loading explanation if needed; do not promise faster hosting. |
| 13 | Responsive / Captive wait | Medium, risk: busy guided dialog disables close; long save may leave user unsure. | Distinguish pre-save cancellation from in-flight save. Explain “Saving” and prevent duplicate submit; retain recovery path on failure. Do not pretend cancellation undoes a committed save. |
| 14 | Efficient / Unnecessary steps | High, confirmed: choose root then Render; a four-step journey for even a name-only addition. | Auto-load tree, one short add-person form with optional story details; preserve optional guided questions for people who want them. |
| 15 | Efficient / Information overload | High, confirmed: numerous account/map/graph inputs shown before a user has selected a task. | Three everyday destinations, contextual actions, read-first screens, advanced settings on demand. |
| 16 | Efficient / System amnesia | Medium, mixed: visited pages preserve drafts (good), person change closes editor, reload loses presentation state. | Preserve same-session task context; explicit discard for dirty drafts; define safe per-account preferences later. Never retain private data after sign-out. |
| 17 | Accurate / Incorrect information | High, confirmed: “Home” displays birth_place. “present” when death date is absent is also an ambiguity risk. | Birthplace label; unknown dates stated as unknown, no inferred living status. Display recorded facts with appropriate uncertainty. |
| 18 | Accurate / Bad prediction | Medium, confirmed: auto-selecting first directory person when no subject exists; stale root/person distinction. | Explicit selection or clearly labeled remembered subject. Filters never silently change the selected profile. |
| 19 | Protective / Irreversible action | High consequence, risk: ownership transfer placed beside routine invites; this audit did not verify recovery semantics. | Advanced owner-only setting with named recipient, consequence and explicit confirmation. Do not invent undo where the API cannot support it. |
| 20 | Protective / Unwanted disclosure | High consequence, boundary: current server role checks/redaction must survive the redesign. | Viewer does not receive medical text or edit controls. Health notes stay collapsed for authorized users; role explanation when granting editor. No new public links or broader visibility. |
| 21 | Protective / Data loss | High, risk: unsaved profile/journey values can be lost on person/circle transition or closing a dialog. | Dirty-state guard and save feedback. Maintain separate behavior for deliberate sign-out, which clears private state. Test partial person-save/relationship failure. |
| 22 | Habituating / Gratuitous redundancy | High, confirmed: duplicate Add, sign-out, circle selection, repeated profile facts, invite vs Add/Update pathways. | One canonical entry point per task per page; consolidate invitations without changing backend authorization. |
| 23 | Habituating / Variable outcome | Medium, risk: same looking controls select a profile vs graph root; viewer forms look like unusable editors. | Stable meaning for person selection, explicit Recenter tree action; viewer read view; clear role-specific actions. |
| 24 | Habituating / Wandering element | Medium, risk: action positions shift with selected subject, status, tabs, and breakpoints. | Stable page header and scoped save footer; equivalent bottom nav on mobile. Check focus after dialogs close. |
| 25 | Habituating / Inconsistent appearance | Medium, confirmed: new workspace shell wraps legacy panel/form styles; differing labels and glyph icons. | One button hierarchy, spacing scale, input style and icon system; consistent dates and capitalization. |
| 26 | Habituating / Ambiguous home | High, confirmed: Home landing, tree destination and numerous overlapping shortcuts compete. | Family tree is the signed-in home. First-use state is embedded there; no extra dashboard. Tradeoff: activity feed loses prominence but stays available under family history. |
| 27 | Beautiful / Poor aesthetic | Medium, evaluative: excessive hero/cover area, gradients and card nesting dilute the homely intention. | Warm neutral canvas, restrained sage/slate, plain typography, useful whitespace, one dominant content surface. Validate with user feedback rather than claiming universal taste. |

## Proposed information architecture

- **Family tree (home):** auto-loaded graph, find person, one Add person action for owner/editor. Node selection opens a compact contextual card. View options is secondary. First-use state offers one Start my family action and a quiet fictional sample alternative.
- **People:** directory first, then a readable profile. Story and Photos are the two primary tabs. Conversation is a section below the story; change history is a labeled secondary action. Editors get Edit profile. Health notes are separate and role protected.
- **Places & time:** recorded life events for an explicitly named person; map and historical context are secondary views. Add place/event is contextual. No repeated empty historical-event blocks and no invented migration paths.
- **Family access:** separate utility destination containing Members and Invitations. Invite new people once; change an existing member's role in their row. Ownership transfer/history under secondary settings.
- **Account:** one persistent location for sign-out, sign-out-all-devices and invitation code. Family switcher is one responsive control, not duplicated inside forms.

Same three main destinations on desktop/mobile; Family access stays visibly labeled in the utility navigation. No hidden hamburger-only primary workflow.

## What changes, what stays

| Change | Reason | Boundary |
|---|---|---|
| Remove standalone Home dashboard | Remove competing starts and duplicated shortcuts | No records removed |
| Remove global Add someone | Prevent unrelated actions on Places/Access | Add remains on Tree and People, one per page |
| Auto-load existing graph | Remove technical Render step | Existing authenticated subgraph endpoint, bounded defaults, explicit view options |
| Contextual relationship sentence | Reduce direction/syntax mistakes | Map labels to existing relationship enum; review sentence before save |
| Short core add form, optional prompts | Respect both quick entry and thoughtful storytelling | Keep duplicate checking and partial-save recovery; no schema redesign |
| Separate family access/account | Stop mixing archive records with account management | Same invitation codes, acceptance, roles and approved tester gate |
| Read-first profile/places | Reduce input density | Editors still reach every existing field; viewers stay read-only |
| Local draft/error feedback | Reduce memory burden and accidental loss | No persistent storage of sensitive notes proposed |

## Prototype coverage and limits

Open index.html via a local HTTP server. The review bar is outside the product and switches example states: Returning family, First visit, Signed out, and Viewer. Included interactions: navigation, search, graph selection, View options, profile tabs, edit/save feedback, add-person form, invite form, account menu, and dirty-discard warning. All data and actions are fictional and remain in memory; reload resets the mockup. There are no API calls, logins, actual invitations, writes to the live database, or security claims based on the role toggle.

The mockup illustrates a recorded-places timeline, not a geographically accurate map. Future production map work must retain existing data permissions and distinguish recorded locations from inferred routes. Visible family member display names in Access are illustrative; implementation must use authorized member display names if available, or a clear non-ambiguous fallback without broadening identity APIs.

## Acceptance plan before implementation/release

1. User reviews this information architecture and prototype before application edits.
2. New-user study: without instructions, locate a person, read their story, add a relative, find who can see records, invite a viewer. Capture hesitation/wrong turns; no invented benchmark results.
3. Owner/editor/viewer/signed-out/no-circle/empty-circle matrices. Verify API denial and redaction, not merely button hiding.
4. Draft preservation across destinations; warnings before person/circle switch; sign-out clears all private UI; in-flight stale results never repopulate another circle.
5. Keyboard navigation, focus return, visible focus, screen-reader names, reduced motion, 200% zoom and narrow viewports.
6. Save/network error/duplicate/partial relationship-save/upload rejection states. Never report success until confirmed by the API.
7. Graph: automatic initial load, selected/root distinction, filter limits, larger families, zoom/pan, recenter and mobile. Keep advanced features accessible without dominating the first view.
8. Existing backend/security regression suite, role-aware browser flows, then approved hosted owner/viewer smoke test. This proposal does not authorize deployment.
