"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  describeGraphNode,
  findDirectionalGraphNode,
} = require("../app/web/graph-utils.js");

test("directional navigation prefers a connected relative", () => {
  const positions = {
    root: { x: 0, y: 0 },
    connected: { x: 100, y: 0 },
    closerButUnrelated: { x: 10, y: 0 },
  };
  const edges = [{ from_person_id: "root", to_person_id: "connected" }];

  assert.equal(
    findDirectionalGraphNode("root", "ArrowRight", positions, edges, Object.keys(positions)),
    "connected"
  );
});

test("directional navigation falls back to the nearest aligned person", () => {
  const positions = {
    root: { x: 0, y: 0 },
    diagonal: { x: 20, y: 80 },
    aligned: { x: 60, y: 2 },
    left: { x: -10, y: 0 },
  };

  assert.equal(
    findDirectionalGraphNode("root", "ArrowRight", positions, [], Object.keys(positions)),
    "aligned"
  );
  assert.equal(
    findDirectionalGraphNode("root", "ArrowLeft", positions, [], Object.keys(positions)),
    "left"
  );
});

test("directional navigation stays put when there is no candidate", () => {
  assert.equal(
    findDirectionalGraphNode("root", "ArrowUp", { root: { x: 0, y: 0 } }, [], ["root"]),
    null
  );
  assert.equal(
    findDirectionalGraphNode("root", "Escape", { root: { x: 0, y: 0 } }, [], ["root"]),
    null
  );
});

test("graph node descriptions expose identity, lifespan, place, relationships, and selection", () => {
  const description = describeGraphNode(
    {
      full_name: "Asha Rao",
      birth_date: "1945-03-02",
      death_date: "2019-08-11",
      birth_place: "Hyderabad",
    },
    2,
    true
  );

  assert.equal(
    description,
    "Asha Rao. 1945-03-02 to 2019-08-11. Born in Hyderabad. 2 relationships. Selected."
  );
  assert.match(describeGraphNode({ full_name: "Dev" }, 1, false), /1 relationship\./);
});
