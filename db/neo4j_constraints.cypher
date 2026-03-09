// Neo4j 5.x constraints and indexes for genealogy graph reads

// Person node uniqueness and lookup
CREATE CONSTRAINT person_person_id_unique IF NOT EXISTS
FOR (p:Person)
REQUIRE p.person_id IS UNIQUE;

CREATE INDEX person_circle_id_idx IF NOT EXISTS
FOR (p:Person)
ON (p.circle_id);

CREATE INDEX person_full_name_idx IF NOT EXISTS
FOR (p:Person)
ON (p.full_name);

// Relationship property indexes for traversal filtering
CREATE INDEX rel_type_idx IF NOT EXISTS
FOR ()-[r:REL]-()
ON (r.type);

CREATE INDEX rel_circle_id_idx IF NOT EXISTS
FOR ()-[r:REL]-()
ON (r.circle_id);

// Optional fulltext index for people search
CREATE FULLTEXT INDEX person_search_idx IF NOT EXISTS
FOR (p:Person)
ON EACH [p.full_name, p.religion, p.occupation];
