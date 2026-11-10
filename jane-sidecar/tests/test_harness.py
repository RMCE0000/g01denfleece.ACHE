from app.harness import build_spine, parse_turn, question_is_copy


def test_a_copied_community_question_is_rejected():
    said = "Yeah... does anybody want a dog? I have 5 up for adoption."
    assert question_is_copy(said, "Does anybody want a dog? I have 5 up for adoption.")
    assert not question_is_copy(said, "Would you bring a dog onto your homestead?")


def test_the_spine_keeps_policy_after_identity():
    spine = build_spine(context="No community question is waiting.")
    assert spine.startswith("# Jane")
    assert spine.index("# You") < spine.index("# Policy")
    assert spine.index("# Policy") < spine.index("# Tools")
    assert "ask_community" in spine
    assert "No community question is waiting." in spine
    assert "JSON object" not in spine.split("# Policy", 1)[1].split("# Tools", 1)[0]


def test_prose_is_a_reply_and_json_names_a_tool():
    assert parse_turn("I'll ask them.") == ("I'll ask them.", [])
    reply, tools = parse_turn(
        '{"reply":"Asking.","tools":[{"name":"ask_community","arguments":{"question":"Would you bring a dog onto your homestead?"}}]}'
    )
    assert reply == "Asking."
    assert tools[0]["name"] == "ask_community"
