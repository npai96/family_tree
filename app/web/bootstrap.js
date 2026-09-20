(function registerFamilyTreeBootstrap(globalScope) {
  "use strict";

  let settled = false;
  const timeoutId = globalScope.setTimeout(() => {
    if (!settled) showFailure("The application code did not start. Check the network connection, then retry.");
  }, 12000);

  function showFailure(messageText) {
    settled = true;
    globalScope.clearTimeout(timeoutId);
    const root = globalScope.document.getElementById("root");
    if (!root) return;
    const section = globalScope.document.createElement("section");
    section.className = "bootstrap-state";
    section.setAttribute("role", "alert");
    const card = globalScope.document.createElement("div");
    card.className = "bootstrap-card";
    const title = globalScope.document.createElement("h1");
    title.textContent = "The interface could not load";
    const message = globalScope.document.createElement("p");
    message.textContent = messageText;
    const retry = globalScope.document.createElement("button");
    retry.type = "button";
    retry.textContent = "Retry loading Viraasat";
    retry.addEventListener("click", () => globalScope.location.reload());
    card.append(title, message, retry);
    section.append(card);
    root.replaceChildren(section);
  }

  globalScope.FamilyTreeBootstrap = Object.freeze({
    complete() {
      settled = true;
      globalScope.clearTimeout(timeoutId);
    },
    fail: showFailure,
  });
})(globalThis);
