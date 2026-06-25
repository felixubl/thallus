"""M8: the life-management vertical slice, built entirely on the kernel.

Success criterion: express People, Tasks, a category, a structural type, an
entity summary, a cross-entity query, and live reactivity — with NO kernel
changes (only the public engine/store/stdlib API). This doubles as the canonical
worked example of the model: nodes are (id, value); every relationship is a
triple whose role is itself a node.
"""

from __future__ import annotations

from thallus import Engine, Node, roles, stdlib


def _role(e: Engine, name: str) -> Node:
    """A role node is just a node with a display name."""
    return e.node().set(roles.LABEL, name)


def _build():
    e = Engine()
    ops = stdlib.install(e)
    types = stdlib.install_types(e)

    # Relationship kinds are nodes.
    name = _role(e, "name")
    email = _role(e, "email")
    phone = _role(e, "phone")
    assigned_to = _role(e, "assigned_to")
    done = _role(e, "done")

    # A Person type: structurally requires a name and an email.
    person = e.define_type("Person", types["structural"])
    e.store.put(person, roles.REQUIRES, name.id)
    e.store.put(person, roles.REQUIRES, email.id)

    # People — entities are pure identity plus relational edges.
    alice_phone = e.literal("555-0001")
    alice = (
        e.node()
        .set(roles.TYPE, person)
        .set(name, e.literal("Alice"))
        .set(email, e.literal("alice@example.com"))
        .set(phone, alice_phone)
    )
    bob_phone = e.literal("555-0002")
    bob = (
        e.node()
        .set(roles.TYPE, person)
        .set(name, e.literal("Bob"))
        .set(email, e.literal("bob@example.com"))
        .set(phone, bob_phone)
    )

    # A category is a node; membership is an edge. A leaf can belong to both an
    # entity (as Alice's phone) and a category (Phone Numbers) at once.
    phone_numbers = _role(e, "Phone Numbers")
    e.store.put(phone_numbers.id, roles.MEMBER, alice_phone.id)
    e.store.put(phone_numbers.id, roles.MEMBER, bob_phone.id)

    # Tasks.
    task1 = e.node().set(assigned_to, alice).set(done, e.literal(False))
    task2 = e.node().set(assigned_to, alice).set(done, e.literal(True))

    return locals()


def _open_tasks(e: Engine, person: Node, assigned_to: Node, done: Node) -> set:
    """Cross-entity query: tasks assigned to `person` that aren't done."""
    result = set()
    for task in e.store.subjects(assigned_to.id, person.id):
        done_node = e.store.one(task, done.id)
        if done_node is not None and e.value(done_node) is False:
            result.add(task)
    return result


def test_person_validates_against_structural_type():
    s = _build()
    e, alice, person, name = s["e"], s["alice"], s["person"], s["name"]
    assert e.validate(alice) is True
    carol = e.node().set(roles.TYPE, person).set(name, e.literal("Carol"))  # no email
    assert e.validate(carol) is False


def test_entity_summary_via_gather():
    s = _build()
    e, alice, ops = s["e"], s["alice"], s["ops"]
    summary = e.application(ops["gather"], alice)
    assert e.value(summary) == {
        "name": "Alice",
        "email": "alice@example.com",
        "phone": "555-0001",
    }


def test_category_collects_shared_leaves():
    s = _build()
    e, phone_numbers = s["e"], s["phone_numbers"]
    members = {e.value(m) for m in e.store.objects(phone_numbers.id, roles.MEMBER)}
    assert members == {"555-0001", "555-0002"}


def test_cross_entity_query_and_reactivity():
    s = _build()
    e, alice = s["e"], s["alice"]
    assigned_to, done, task1 = s["assigned_to"], s["done"], s["task1"]

    assert _open_tasks(e, alice, assigned_to, done) == {task1.id}
    task1.set(done, e.literal(True))  # complete it
    assert _open_tasks(e, alice, assigned_to, done) == set()


def test_summary_reacts_to_attribute_change():
    s = _build()
    e, alice, phone, ops = s["e"], s["alice"], s["phone"], s["ops"]
    summary = e.application(ops["gather"], alice)
    assert e.value(summary)["phone"] == "555-0001"
    alice.set(phone, e.literal("555-9999"))  # Alice got a new phone
    assert e.value(summary)["phone"] == "555-9999"
