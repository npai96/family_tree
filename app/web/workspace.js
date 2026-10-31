/* Navigation and presentation only. App owns identity, permissions, and all API calls. */
(function (root) {
  const destinations = [
    { id: "tree", title: "Family tree", icon: "♧", description: "Explore the people and connections in your family." },
    { id: "people", title: "People", icon: "◎", description: "Stories and details, one person at a time." },
    { id: "places", title: "Places & time", icon: "⌖", description: "Recorded places and moments in your family’s lives." },
    { id: "circle", title: "Family access", icon: "◌", description: "People who can open this family archive." },
  ];
  function pageFromHash(hash) {
    const value = String(hash || "").replace(/^#/, "");
    if (value === "access") return "circle";
    return destinations.some((page) => page.id === value) ? value : "tree";
  }
  function initials(name) {
    return String(name || "?").trim().split(/\s+/).slice(0, 2).map((part) => Array.from(part)[0] || "").join("");
  }
  function filterPeople(people, query) {
    const needle = query.trim().toLocaleLowerCase();
    return people.filter((person) => [person.full_name, person.birth_place, person.occupation].some((value) => String(value || "").toLocaleLowerCase().includes(needle)));
  }
  function Workspace(props) {
    const React = root.React;
    const h = React.createElement;
    const { useEffect, useRef, useState } = React;
    const { page, onNavigate, isAuthenticated, panels, persons, selectedPerson, selectedPersonId, onSelectPerson, selectedCircle, circles, canEditRecords } = props;
    const [visited, setVisited] = useState(() => new Set([page]));
    const [personTab, setPersonTab] = useState("story");
    const [visitedTabs, setVisitedTabs] = useState(() => new Set(["story"]));
    const [query, setQuery] = useState("");
    const [inviteOpen, setInviteOpen] = useState(false);
    const [editing, setEditing] = useState(false);
    const [dirty, setDirty] = useState(false);
    const [saving, setSaving] = useState(false);
    const [saveMessage, setSaveMessage] = useState("");
    const guard = () => !saving && (!dirty || window.confirm("Discard these unsaved profile changes?"));
    function choosePerson(id) { if (id !== selectedPersonId) onSelectPerson(id); }
    useEffect(() => {
      props.onRegisterSelectionGuard(() => { if (!guard()) return false; setDirty(false); return true; });
      return () => props.onRegisterSelectionGuard(null);
    }, [dirty, saving]);
    function chooseCircle(id) { if (id === selectedCircle) return; if (guard()) props.onSelectCircle(id); }
    useEffect(() => {
      const warn = (event) => { if (dirty || saving) { event.preventDefault(); event.returnValue = ""; } };
      window.addEventListener("beforeunload", warn);
      return () => window.removeEventListener("beforeunload", warn);
    }, [dirty, saving]);
    const headingRef = useRef(null);
    const previousPage = useRef(page);
    const circle = circles.find((item) => item.id === selectedCircle);
    const circleName = circle?.name || "Your family archive";
    const destination = destinations.find((item) => item.id === page) || destinations[0];

    useEffect(() => {
      setVisited((current) => new Set([...current, page]));
      document.title = `${destination.title} | Viraasat`;
      if (previousPage.current !== page) {
        headingRef.current?.focus({ preventScroll: true });
        window.scrollTo({ top: 0 });
        previousPage.current = page;
      }
    }, [page, destination.title]);
    useEffect(() => { setEditing(false); setDirty(false); setSaveMessage(""); }, [selectedPersonId]);
    useEffect(() => {
      if (isAuthenticated && ["people", "places"].includes(page) && !selectedPersonId && persons.length) onSelectPerson(persons[0].id);
    }, [page, selectedPersonId, persons, isAuthenticated, onSelectPerson]);

    const button = (text, action, className = "ws-button", extra = {}) => h("button", { type: "button", className, onClick: action, ...extra }, text);
    const avatar = (name, className = "") => h("span", { className: `ws-avatar ${className}`, "aria-hidden": true }, initials(name));
    const goPerson = (person) => { choosePerson(person.id); setPersonTab("story"); onNavigate("people"); };
    const livePanel = (element, active = undefined) => element ? React.cloneElement(element, { ...(active === undefined ? {} : { active }) }) : null;
    const tabs = [{ id: "story", label: "Story" }, { id: "media", label: "Photos" }];
    function changeTab(id) { setPersonTab(id); setVisitedTabs((current) => new Set([...current, id])); }
    function labelFields(element) {
      if (Array.isArray(element)) return element.map(labelFields);
      if (!React.isValidElement(element)) return element;
      const label = element.props["aria-label"];
      if (["input", "textarea"].includes(element.type) && label) return h("label", { key: element.key, className: "ws-field" }, h("span", null, label), element);
      if (!element.props.children) return element;
      return React.cloneElement(element, {}, React.Children.map(element.props.children, labelFields));
    }
    const nav = (mobile = false) => h("nav", { className: mobile ? "ws-mobile-nav" : "ws-navigation", "aria-label": mobile ? "Mobile workspace" : "Family workspace" }, destinations.filter((item) => item.id !== "circle").map((item) => button(
      [h("span", { key: "icon", className: "ws-nav-icon", "aria-hidden": true }, item.icon), h("span", { key: "label" }, mobile ? ({ people: "People", places: "Places", tree: "Tree", circle: "Circle" }[item.id] || item.title) : item.title)],
      () => onNavigate(item.id), `ws-nav-item ${page === item.id ? "is-active" : ""}`, { key: item.id, "aria-current": page === item.id ? "page" : undefined }
    )));
    const circlePicker = h("label", { className: "ws-circle-picker" }, h("span", null, "Family circle"), h("select", { value: selectedCircle, onChange: (event) => chooseCircle(event.target.value), disabled: !isAuthenticated, "aria-label": "Active family circle" }, h("option", { value: "" }, "Choose a circle"), circles.map((item) => h("option", { key: item.id, value: item.id }, item.name))));
    const empty = (title, copy, target = "circle") => h("div", { className: "ws-empty" }, h("h2", null, title), h("p", null, copy), button(target === "circle" ? "Open Family access" : "Explore family tree", () => onNavigate(target), "ws-button ws-primary"));
    const addButton = canEditRecords && selectedCircle ? button("＋ Add person", props.onAddPerson, "ws-button ws-primary") : null;

    // Compose existing panels without duplicating their account controls or API handlers.
    function accountPart(keys) {
      return React.Children.toArray(panels.account?.props.children).filter((child) =>
        keys.some((key) => child.key === key || child.key === `.$${key}`));
    }
    function tree() {
      if (!selectedCircle) return empty("Start your family archive", "Create a private family or accept an invitation in Family access.");
      return h(React.Fragment, null,
        h("section", { className: "ws-tree-layout" }, panels.tree,
          selectedPerson && h("aside", { className: "ws-inspector" }, avatar(selectedPerson.full_name), h("h2", null, selectedPerson.full_name), h("p", { className: "muted" }, selectedPerson.birth_place ? `Birthplace: ${selectedPerson.birth_place}` : "Birthplace not recorded"), button("Read their story →", () => goPerson(selectedPerson), "ws-button"))),
        h("div", { className: "ws-tree-tools" }, h("span", null, "Select a person to explore their story."), button("Zoom +", props.onZoomIn), button("Zoom −", props.onZoomOut), button("Fit tree", props.onFit)),
        livePanel(panels.relationships)
      );
    }
    function storyPanel() {
      const fields = [["Born", selectedPerson.birth_date], ["Died", selectedPerson.death_date], ["Birthplace", selectedPerson.birth_place], ["Work", selectedPerson.occupation], ["Hobbies", selectedPerson.hobbies], ["Personality", selectedPerson.personality], ["Religion", selectedPerson.religion], ["Sex", selectedPerson.sex]];
      return h(React.Fragment, null,
        h("div", { hidden: editing },

          h("p", { className: "ws-biography" }, selectedPerson.bio_text || "No story has been recorded yet."),
          h("dl", { className: "ws-facts" }, fields.filter(([, value]) => value).map(([label, value]) => h("div", { key: label }, h("dt", null, label), h("dd", null, value))))
        ),
        !canEditRecords && h("p", { className: "sensitive-field-notice" }, "Medical notes are visible only to owners and editors."),
        canEditRecords && h("details", { hidden: editing, className: "ws-health" }, h("summary", null, "Health notes · owners and editors only"), h("p", null, selectedPerson.medical_notes || "No health notes recorded.")),
        h("div", { hidden: !editing }, profileEditor(panels.profile)),
        saveMessage && h("p", { role: "status", className: "ws-save-feedback" }, saveMessage),
        livePanel(panels.discussion),
        livePanel(panels.revisions)
      );
    }
    function profileEditor(element) {
      if (!React.isValidElement(element)) return element;
      if (element.type === "form") return React.cloneElement(element, {
        onChange: () => { setDirty(true); setSaveMessage("Unsaved changes"); },
        onSubmit: async (event) => {
          event.preventDefault();
          if (saving) return;
          setSaving(true); setSaveMessage("Saving…");
          try { await element.props.onSubmit(event); setDirty(false); setSaveMessage("Changes saved."); }
          catch (error) { setSaveMessage(error.message || "Could not save. Your draft is still here."); }
          finally { setSaving(false); }
        },
      }, h("fieldset", { disabled: saving }, labelFields(element.props.children)));
      return React.cloneElement(element, {}, React.Children.map(element.props.children, profileEditor));
    }
    function people() {
      return !selectedCircle ? empty("Choose a family circle", "People and stories belong to your selected circle.") : h("div", { className: "ws-people-layout" },
        h("label", { className: "ws-mobile-person" }, "Person", h("select", { value: selectedPersonId || "", onChange: (event) => choosePerson(event.target.value) }, h("option", { value: "" }, "Choose a person"), persons.map((person) => h("option", { key: person.id, value: person.id }, person.full_name)))),
        h("aside", { className: "ws-directory" }, h("label", { className: "ws-search" }, h("span", null, "Find a person"), h("input", { type: "search", value: query, onChange: (event) => setQuery(event.target.value), placeholder: "Name, place, or occupation" })), h("p", { className: "ws-eyebrow" }, `${persons.length} PEOPLE`), filterPeople(persons, query).map((person) => button([avatar(person.full_name), h("span", { key: "text" }, h("strong", null, person.full_name), h("small", null, person.occupation || person.birth_place || "Family member"))], () => choosePerson(person.id), `ws-directory-person ${person.id === selectedPersonId ? "is-active" : ""}`, { key: person.id, "aria-pressed": person.id === selectedPersonId })), !filterPeople(persons, query).length && h("p", { className: "muted" }, persons.length ? "No matching people." : "Add your first family member to begin.")),
        h("article", { className: "ws-person-sheet" }, selectedPerson ? h(React.Fragment, null,

          h("div", { className: "ws-person-body" }, h("div", { className: "ws-person-heading" }, h("div", null,  h("h2", null, selectedPerson.full_name), h("p", { className: "muted" }, [selectedPerson.birth_date, selectedPerson.birth_place, selectedPerson.occupation].filter(Boolean).join(" · "))), canEditRecords && button(editing ? "Close editor" : "Edit profile", () => { if (!editing || guard()) { setDirty(false); setEditing(!editing); changeTab("story"); } })),
            h("div", { className: "ws-person-tabs", role: "tablist", "aria-label": "Person details", onKeyDown: (event) => { if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) return; event.preventDefault(); const index = tabs.findIndex((tab) => tab.id === personTab); const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length; changeTab(tabs[next].id); document.getElementById(`ws-tab-${tabs[next].id}`)?.focus(); } }, tabs.map((tab) => button(tab.label, () => changeTab(tab.id), `ws-tab ${personTab === tab.id ? "is-active" : ""}`, { key: tab.id, id: `ws-tab-${tab.id}`, role: "tab", "aria-selected": personTab === tab.id, "aria-controls": `ws-panel-${tab.id}`, tabIndex: personTab === tab.id ? 0 : -1 }))),
            tabs.map((tab) => h("section", { key: tab.id, id: `ws-panel-${tab.id}`, role: "tabpanel", "aria-labelledby": `ws-tab-${tab.id}`, hidden: personTab !== tab.id, className: "ws-person-panel" },
              tab.id === "story" ? storyPanel() : visitedTabs.has(tab.id) ? livePanel(panels[tab.id], personTab === tab.id && page === "people") : null))
          )) : h("div", { className: "ws-empty" }, h("h2", null, "Choose someone from the family"), h("p", null, "Their story, photos, and conversations will appear here.")))
      );
    }
    function places() {
      return !selectedCircle ? empty("Choose a family circle", "Places and family milestones will appear here.") : h(React.Fragment, null,
        h("label", { className: "ws-place-person" }, "Showing records for", h("select", { value: selectedPersonId || "", onChange: (event) => choosePerson(event.target.value) }, h("option", { value: "" }, "Choose a person"), persons.map((person) => h("option", { key: person.id, value: person.id }, person.full_name)))),
        h("div", { className: "ws-places-grid" }, livePanel(panels.places, page === "places"), livePanel(panels.timeline)),
        h("details", { className: "card" }, h("summary", null, "Historical context"), livePanel(panels.context), panels.lineage)
      );
    }
    function circlePage() {
      return h("div", { className: "ws-access" },
        !selectedCircle && h("section", { className: "card" }, h("h2", null, "Start a family"), accountPart(["f2", "sample"])),
        selectedCircle && livePanel(panels.membership, page === "circle"),
        inviteOpen && h("section", { className: "card", "aria-label": "Invite someone" }, h("h2", null, "Invite someone"), panels.inviteForm),
        livePanel(panels.invitations, page === "circle"),
        selectedCircle && h("details", { className: "card" }, h("summary", null, "Family settings & history"), accountPart(["f2"]), livePanel(panels.ownership), livePanel(panels.requests), livePanel(panels.audit))
      );
    }
    const renderers = { tree, people, places, circle: circlePage };
    return h("div", { className: `family-workspace ${!isAuthenticated ? "ws-signed-out" : ""}` },
      h("a", { className: "ws-skip", href: "#ws-main", onClick: (event) => { event.preventDefault(); document.getElementById("ws-main")?.focus(); } }, "Skip to content"),
      isAuthenticated && h("aside", { className: "ws-sidebar" },
        h("div", { className: "ws-brand" }, h("div", null, h("strong", null, "Viraasat"), h("small", null, "Your family, remembered."))), circlePicker, nav(),
        h("div", { className: "ws-sidebar-bottom" }, button("Family access", () => onNavigate("circle"), `ws-nav-item ${page === "circle" ? "is-active" : ""}`),
          h("details", { className: "ws-account-menu" }, h("summary", null, avatar(props.activeUserName), h("span", null, h("strong", null, props.activeUserName || "Your account"), h("small", null, props.activeCircleRole || "No family selected"))),
            accountPart(["account-code", "signout-all"]),
            button("Sign out", props.onSignOut, "ws-text-button"),
            !props.managedAuthAvailable && h("details", null, h("summary", null, "Local test accounts"), accountPart(["f1", "l1", "s1"]))))) ,
      h("div", { className: "ws-content" }, h("main", { id: "ws-main", className: "ws-main", tabIndex: -1 },
        !isAuthenticated ? h("div", { className: "ws-auth" }, h("h2", { className: "ws-auth-brand" }, "Viraasat"), panels.tree, !props.managedAuthAvailable && panels.account) : h(React.Fragment, null,
          h("header", { className: "ws-page-heading" }, h("div", null, h("h1", { ref: headingRef, tabIndex: -1 }, destination.title), h("p", null, page === "tree" ? `${circleName} · ${persons.length} people` : destination.description)), ["tree", "people"].includes(page) && addButton, page === "circle" && props.canManageMembers && button(inviteOpen ? "Close invitation form" : "Invite someone", () => setInviteOpen(!inviteOpen), "ws-button ws-primary")),
          h("p", { className: "ws-status", role: "status", "aria-live": "polite" }, props.status),
          dirty && page !== "people" && h("div", { className: "ws-draft-banner" }, "Your profile has unsaved changes. ", button("Return to draft", () => onNavigate("people"))),
          destinations.map((item) => h("div", { key: item.id, hidden: page !== item.id, className: `ws-page ws-page-${item.id}` }, visited.has(item.id) || page === item.id ? renderers[item.id]() : null))
        )
      )), isAuthenticated && nav(true)
    );
  }
  const api = { Workspace, pageFromHash, filterPeople, initials, destinations };
  root.FamilyTreeWorkspace = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(globalThis);
