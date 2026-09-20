"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");


class FakeElement {
  constructor(tagName) {
    this.tagName = tagName;
    this.attributes = {};
    this.children = [];
    this.events = {};
    this.textContent = "";
    this.className = "";
    this.type = "";
  }

  setAttribute(name, value) {
    this.attributes[name] = value;
  }

  addEventListener(name, callback) {
    this.events[name] = callback;
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = children;
  }
}


function readFrontendAssets() {
  const webRoot = path.join(__dirname, "..", "app", "web");
  const htmlPath = path.join(webRoot, "index.html");
  const html = fs.readFileSync(htmlPath, "utf8");
  const applicationScript = fs.readFileSync(path.join(webRoot, "app.js"), "utf8");
  const bootstrapScript = fs.readFileSync(path.join(webRoot, "bootstrap.js"), "utf8");
  return { applicationScript, bootstrapScript, html };
}


test("bootstrap shows a retryable alert when verified browser dependencies are unavailable", () => {
  const { applicationScript, bootstrapScript } = readFrontendAssets();
  const root = new FakeElement("div");
  let reloaded = false;
  let watchdog = null;
  const context = {
    document: {
      createElement: (tagName) => new FakeElement(tagName),
      getElementById: (id) => (id === "root" ? root : null),
    },
    location: { reload: () => { reloaded = true; } },
    setTimeout: (callback) => { watchdog = callback; return 1; },
    clearTimeout: () => {},
  };
  context.globalThis = context;

  vm.runInNewContext(bootstrapScript, context);
  vm.runInNewContext(applicationScript, context);

  assert.equal(root.children.length, 1);
  const section = root.children[0];
  assert.equal(section.attributes.role, "alert");
  const [card] = section.children;
  const [title, message, retry] = card.children;
  assert.equal(title.textContent, "The interface could not load");
  assert.match(message.textContent, /React, ReactDOM, D3, graph utilities/);
  assert.equal(retry.textContent, "Retry loading Viraasat");
  retry.events.click();
  assert.equal(reloaded, true);
  assert.equal(typeof watchdog, "function");
});


test("bootstrap watchdog reports when the main application asset never starts", () => {
  const { bootstrapScript } = readFrontendAssets();
  const root = new FakeElement("div");
  let watchdog = null;
  const context = {
    document: {
      createElement: (tagName) => new FakeElement(tagName),
      getElementById: (id) => (id === "root" ? root : null),
    },
    location: { reload: () => {} },
    setTimeout: (callback) => { watchdog = callback; return 1; },
    clearTimeout: () => {},
  };
  context.globalThis = context;

  vm.runInNewContext(bootstrapScript, context);
  watchdog();

  const message = root.children[0].children[0].children[1];
  assert.match(message.textContent, /application code did not start/i);
});


test("vendored production scripts are exact-versioned and match their integrity hashes", () => {
  const { html } = readFrontendAssets();
  assert.match(
    html,
    /integrity="sha384-DGyLxAyjq0f9SPpVevD6IgztCFlnMF6oW\/XQGmfe\+IsZ8TqEiDrcHkMLKI6fiB\/Z"[\s\S]*\/assets\/vendor\/react-18\.3\.1\.production\.min\.js/
  );
  assert.match(
    html,
    /integrity="sha384-gTGxhz21lVGYNMcdJOyq01Edg0jhn\/c22nsx0kyqP0TxaV5WVdsSH1fSDUf5YJj1"[\s\S]*\/assets\/vendor\/react-dom-18\.3\.1\.production\.min\.js/
  );
  assert.match(
    html,
    /integrity="sha384-CjloA8y00\+1SDAUkjs099PVfnY2KmDC2BZnws9kh8D\/lX1s46w6EPhpXdqMfjK6i"[\s\S]*\/assets\/vendor\/d3-7\.9\.0\.min\.js/
  );

  const webRoot = path.join(__dirname, "..", "app", "web");
  const protectedScripts = Array.from(
    html.matchAll(/integrity="(sha384-[^"]+)"[\s\S]*?src="\/assets\/([^"]+)"/g),
    (match) => ({ expected: match[1], relativePath: match[2] })
  );
  assert.equal(protectedScripts.length, 3);
  protectedScripts.forEach(({ expected, relativePath }) => {
    const bytes = fs.readFileSync(path.join(webRoot, relativePath));
    const actual = `sha384-${crypto.createHash("sha384").update(bytes).digest("base64")}`;
    assert.equal(actual, expected);
  });
});
