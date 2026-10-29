/* Navigation and presentation only. App owns identity, permissions, and all API calls. */
(function (root) {
  const destinations = [
    { id: "home", title: "Home", icon: "⌂", eyebrow: "YOUR FAMILY ARCHIVE", description: "Pick up a story, explore a connection, or add what you remember." },
    { id: "tree", title: "Family tree", icon: "♧", eyebrow: "EXPLORE CONNECTIONS", description: "Start with a person and see how everyone connects." },
    { id: "people", title: "People & stories", icon: "◎", eyebrow: "THE PEOPLE BEHIND THE TREE", description: "A page for each person, with room for more than dates and names." },
    { id: "places", title: "Places & time", icon: "⌖", eyebrow: "ROOTS AND ROUTES", description: "Follow where the family lived and put their years in context." },
    { id: "circle", title: "Our circle", icon: "◌", eyebrow: "KEEPING THIS TOGETHER", description: "Invite family, manage access, and review changes in one place." },
  ];
  function pageFromHash(hash) {
    const value = String(hash || "").replace(/^#/, "");
    return destinations.some((page) => page.id === value) ? value : "home";
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
    const [editing, setEditing] = useState(false);
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
    useEffect(() => { setEditing(false); }, [selectedPersonId]);
    useEffect(() => {
      if (isAuthenticated && ["people", "places"].includes(page) && !selectedPersonId && persons.length) onSelectPerson(persons[0].id);
    }, [page, selectedPersonId, persons, isAuthenticated, onSelectPerson]);

    const button = (text, action, className = "ws-button", extra = {}) => h("button", { type: "button", className, onClick: action, ...extra }, text);
    const avatar = (name, className = "") => h("span", { className: `ws-avatar ${className}`, "aria-hidden": true }, initials(name));
    const goPerson = (person) => { onSelectPerson(person.id); setPersonTab("story"); onNavigate("people"); };
    const livePanel = (element, active = undefined) => element ? React.cloneElement(element, { ...(active === undefined ? {} : { active }) }) : null;
    const tabs = [{ id: "story", label: "Story" }, { id: "media", label: "Photos & media" }, { id: "discussion", label: "Conversation" }, { id: "revisions", label: "History" }];
    function changeTab(id) { setPersonTab(id); setVisitedTabs((current) => new Set([...current, id])); }
    function labelFields(element) {
      if (!React.isValidElement(element)) return element;
      const label = element.props["aria-label"];
      if (["input", "textarea"].includes(element.type) && label) return h("label", { key: element.key, className: "ws-field" }, h("span", null, label), element);
      if (!element.props.children) return element;
      return React.cloneElement(element, {}, React.Children.map(element.props.children, labelFields));
    }
    const nav = (mobile = false) => h("nav", { className: mobile ? "ws-mobile-nav" : "ws-navigation", "aria-label": mobile ? "Mobile workspace" : "Family workspace" }, destinations.map((item) => button(
      [h("span", { key: "icon", className: "ws-nav-icon", "aria-hidden": true }, item.icon), h("span", { key: "label" }, mobile ? ({ people: "People", places: "Places", tree: "Tree", circle: "Circle" }[item.id] || item.title) : item.title)],
      () => onNavigate(item.id), `ws-nav-item ${page === item.id ? "is-active" : ""}`, { key: item.id, "aria-current": page === item.id ? "page" : undefined }
    )));
    const circlePicker = h("label", { className: "ws-circle-picker" }, h("span", null, "Family circle"), h("select", { value: selectedCircle, onChange: (event) => props.onSelectCircle(event.target.value), disabled: !isAuthenticated, "aria-label": "Active family circle" }, h("option", { value: "" }, "Choose a circle"), circles.map((item) => h("option", { key: item.id, value: item.id }, item.name))));
    const empty = (title, copy, target = "circle") => h("div", { className: "ws-empty" }, h("h2", null, title), h("p", null, copy), button(target === "circle" ? "Open Our circle" : "Explore family tree", () => onNavigate(target), "ws-button ws-primary"));
    const addButton = canEditRecords && selectedCircle ? button("＋ Add someone", props.onAddPerson, "ws-button ws-primary") : null;

    function home() {
      return h(React.Fragment, null,
        h("section", { className: "ws-welcome" },
          h("div", { className: "ws-welcome-copy" }, h("p", { className: "ws-eyebrow" }, circleName), h("h2", null, "A home for your family’s stories."), h("p", null, "Explore the people, places, and moments that make up this family. Add what you know, then invite others to fill in what you don’t."), h("div", { className: "ws-actions" }, button(selectedCircle ? "Explore family tree ↗" : "Create or join a circle →", () => onNavigate(selectedCircle ? "tree" : "circle"), "ws-button ws-cream"), addButton)),
          h("div", { className: "ws-family-art", "aria-hidden": true }, persons.slice(0, 4).map((person, index) => h("span", { key: person.id, className: `ws-keepsake ws-keepsake-${index}` }, initials(person.full_name))), h("p", null, `${persons.length} people · ${props.relationships.length} ${props.relationships.length === 1 ? "connection" : "connections"}`))
        ),
        !selectedCircle ? empty("Start your family circle", "Create a private circle or accept an invitation in Our circle.") : h("div", { className: "ws-home-columns" },
          h("section", null, h("p", { className: "ws-eyebrow" }, "PEOPLE IN YOUR CIRCLE"), h("h2", null, "Spend a moment with the family"), persons.length ? h("div", { className: "ws-home-people" }, persons.slice(0, 4).map((person) => button([avatar(person.full_name), h("span", { key: "name" }, h("strong", null, person.full_name), h("small", null, [person.occupation, person.birth_place].filter(Boolean).join(" · ") || "Open their story")), h("span", { key: "arrow", "aria-hidden": true }, "↗")], () => goPerson(person), "ws-person-preview", { key: person.id }))) : h("p", null, "This circle has no people yet. Begin with someone you know."), h("div", { className: "ws-home-shortcuts" }, button("⌖ Follow the places →", () => onNavigate("places"), "ws-shortcut"), button("◌ Bring someone in →", () => onNavigate("circle"), "ws-shortcut"))),
          h("section", { className: "ws-recent" }, h("p", { className: "ws-eyebrow" }, "AROUND THE CIRCLE"), h("h2", null, "Recent activity"), props.auditLogs.length ? h("ul", null, props.auditLogs.slice(0, 5).map((entry) => h("li", { key: entry.id }, h("strong", null, `${String(entry.action).replaceAll("_", " ")} · ${String(entry.entity_type).replaceAll("_", " ")}`), h("small", null, entry.created_at?.slice(0, 10))))) : h("p", { className: "muted" }, "No activity is available to show yet."), button("View circle activity →", () => onNavigate("circle"), "ws-text-button"))
        )
      );
    }
    function tree() {
      return h(React.Fragment, null, !selectedCircle && empty("Choose a family circle", "Your family tree will appear here after you select a circle."),
        h("div", { className: "ws-tree-tools" }, button("Zoom +", props.onZoomIn), button("Zoom −", props.onZoomOut), button("Fit tree", props.onFit)),
        h("div", { className: "ws-tree-layout" }, panels.tree, h("aside", { className: "ws-inspector" }, h("p", { className: "ws-eyebrow" }, "SELECTED PERSON"), selectedPerson ? h(React.Fragment, null, avatar(selectedPerson.full_name), h("h2", null, selectedPerson.full_name), h("p", { className: "muted" }, [selectedPerson.occupation, selectedPerson.birth_place].filter(Boolean).join(" · ")), h("p", null, selectedPerson.bio_text || "There’s room for their story here."), button("Open their story ↗", () => goPerson(selectedPerson), "ws-button ws-primary"), button("See places & time →", () => onNavigate("places"), "ws-text-button")) : h("p", null, "Choose a person in the tree to see their details."))),
        h("div", { className: "ws-relationship-tools" }, livePanel(panels.relationships))
      );
    }
    function storyPanel() {
      const fields = [["Born", selectedPerson.birth_date], ["Died", selectedPerson.death_date], ["Home", selectedPerson.birth_place], ["Work", selectedPerson.occupation], ["Hobbies", selectedPerson.hobbies], ["Personality", selectedPerson.personality], ["Religion", selectedPerson.religion], ["Sex", selectedPerson.sex]];
      return h(React.Fragment, null,
        h("div", { hidden: editing },
          h("p", { className: "ws-eyebrow" }, "THEIR STORY"),
          h("p", { className: "ws-biography" }, selectedPerson.bio_text || "No story has been recorded yet."),
          h("dl", { className: "ws-facts" }, fields.filter(([, value]) => value).map(([label, value]) => h("div", { key: label }, h("dt", null, label), h("dd", null, value))))
        ),
        !canEditRecords && h("p", { className: "sensitive-field-notice" }, "Medical notes are visible only to owners and editors."),
        h("div", { hidden: !editing }, labelFields(panels.profile))
      );
    }
    function people() {
      return !selectedCircle ? empty("Choose a family circle", "People and stories belong to your selected circle.") : h("div", { className: "ws-people-layout" },
        h("aside", { className: "ws-directory" }, h("label", { className: "ws-search" }, h("span", null, "Find a person"), h("input", { type: "search", value: query, onChange: (event) => setQuery(event.target.value), placeholder: "Name, place, or occupation" })), h("p", { className: "ws-eyebrow" }, `${persons.length} PEOPLE`), filterPeople(persons, query).map((person) => button([avatar(person.full_name), h("span", { key: "text" }, h("strong", null, person.full_name), h("small", null, person.occupation || person.birth_place || "Family member"))], () => onSelectPerson(person.id), `ws-directory-person ${person.id === selectedPersonId ? "is-active" : ""}`, { key: person.id, "aria-pressed": person.id === selectedPersonId })), !filterPeople(persons, query).length && h("p", { className: "muted" }, persons.length ? "No matching people." : "Add your first family member to begin.")),
        h("article", { className: "ws-person-sheet" }, selectedPerson ? h(React.Fragment, null,
          h("div", { className: "ws-person-cover" }, avatar(selectedPerson.full_name)),
          h("div", { className: "ws-person-body" }, h("div", { className: "ws-person-heading" }, h("div", null, h("p", { className: "ws-eyebrow" }, "PERSON PROFILE"), h("h2", null, selectedPerson.full_name), h("p", { className: "muted" }, [selectedPerson.birth_date, selectedPerson.birth_place, selectedPerson.occupation].filter(Boolean).join(" · "))), canEditRecords && button(editing ? "Close editor" : "Edit details", () => { setEditing(!editing); changeTab("story"); })),
            h("div", { className: "ws-person-tabs", role: "tablist", "aria-label": "Person details", onKeyDown: (event) => { if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) return; event.preventDefault(); const index = tabs.findIndex((tab) => tab.id === personTab); const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length; changeTab(tabs[next].id); document.getElementById(`ws-tab-${tabs[next].id}`)?.focus(); } }, tabs.map((tab) => button(tab.label, () => changeTab(tab.id), `ws-tab ${personTab === tab.id ? "is-active" : ""}`, { key: tab.id, id: `ws-tab-${tab.id}`, role: "tab", "aria-selected": personTab === tab.id, "aria-controls": `ws-panel-${tab.id}`, tabIndex: personTab === tab.id ? 0 : -1 }))),
            tabs.map((tab) => h("section", { key: tab.id, id: `ws-panel-${tab.id}`, role: "tabpanel", "aria-labelledby": `ws-tab-${tab.id}`, hidden: personTab !== tab.id, className: "ws-person-panel" },
              tab.id === "story" ? storyPanel() : visitedTabs.has(tab.id) ? livePanel(panels[tab.id], personTab === tab.id && page === "people") : null))
          )) : h("div", { className: "ws-empty" }, h("h2", null, "Choose someone from the family"), h("p", null, "Their story, photos, and conversations will appear here.")))
      );
    }
    function places() {
      return !selectedCircle ? empty("Choose a family circle", "Places and family milestones will appear here.") : h(React.Fragment, null,
        h("label", { className: "ws-place-person" }, "Explore places for", h("select", { value: selectedPersonId || "", onChange: (event) => onSelectPerson(event.target.value) }, h("option", { value: "" }, "Choose a person"), persons.map((person) => h("option", { key: person.id, value: person.id }, person.full_name)))),
        h("div", { className: "ws-places-grid" }, h("div", null, livePanel(panels.places, page === "places")), h("div", null, livePanel(panels.timeline), livePanel(panels.context))),
        panels.lineage
      );
    }
    function circlePage() {
      return h("div", { className: "ws-circle-grid" }, h("div", null, panels.account, livePanel(panels.membership), livePanel(panels.invitations)), h("div", null, h("section", { className: "ws-privacy-card" }, h("p", { className: "ws-eyebrow" }, "A SHARED, PRIVATE ARCHIVE"), h("h2", null, "Built together, kept private."), h("p", null, "Circle membership controls who can see this family. Owners manage access, editors contribute, and viewers read shared stories."), h("p", null, "Medical notes are available only to owners and editors.")), livePanel(panels.requests), livePanel(panels.audit)));
    }
    const renderers = { home, tree, people, places, circle: circlePage };
    return h("div", { className: "family-workspace" },
      h("a", { className: "ws-skip", href: "#ws-main", onClick: (event) => { event.preventDefault(); document.getElementById("ws-main")?.focus(); } }, "Skip to content"),
      h("aside", { className: "ws-sidebar" }, h("div", { className: "ws-brand" }, h("span", { "aria-hidden": true }, "V"), h("div", null, h("strong", null, "Viraasat"), h("small", null, "A place for family stories"))), circlePicker, h("p", { className: "ws-nav-caption" }, "YOUR SPACE"), nav(), h("div", { className: "ws-sidebar-bottom" }, h("p", null, "Small details become the stories we keep."), h("div", { className: "ws-account" }, avatar(isAuthenticated ? props.activeUserName : "V"), h("span", null, h("strong", null, isAuthenticated ? props.activeUserName || "Signed in" : "Welcome"), h("small", null, isAuthenticated ? props.activeCircleRole || "Choose a circle" : "Sign in to continue"))), isAuthenticated && button("Sign out", props.onSignOut, "ws-text-button"))),
      h("div", { className: "ws-content" }, h("header", { className: "ws-topbar" }, h("div", { className: "ws-breadcrumb" }, h("span", null, circleName), h("span", { "aria-hidden": true }, "/"), h("strong", null, destination.title)), h("div", { className: "ws-top-actions" }, h("span", { className: `auth-mode-chip ${props.authModeClass}` }, props.authModeLabel), addButton)),
        h("main", { id: "ws-main", className: "ws-main", tabIndex: -1 },
          h("div", { className: "ws-mobile-circle" }, circlePicker),
          !isAuthenticated ? h("div", { className: "ws-auth" }, panels.tree, !props.managedAuthAvailable && panels.account) : h(React.Fragment, null,
            page !== "home" && h("div", { className: "ws-page-heading" }, h("p", { className: "ws-eyebrow" }, destination.eyebrow), h("h1", { ref: headingRef, tabIndex: -1 }, destination.title), h("p", null, destination.description)),
            page === "home" && h("h1", { className: "sr-only", ref: headingRef, tabIndex: -1 }, "Family home"),
            h("p", { className: "ws-status", role: "status", "aria-live": "polite" }, props.status),
            destinations.map((item) => h("div", { key: item.id, hidden: page !== item.id, className: `ws-page ws-page-${item.id}` }, visited.has(item.id) || page === item.id ? renderers[item.id]() : null))
          )
        )
      ), nav(true)
    );
  }
  const api = { Workspace, pageFromHash, filterPeople, initials, destinations };
  root.FamilyTreeWorkspace = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(globalThis);
