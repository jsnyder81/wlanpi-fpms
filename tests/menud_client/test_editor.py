"""The button editor for string and form prompts."""

from fpms.modules.menud_client.editor import CHARS, PromptEditor

STRING = {"prompt_id": "pstr1", "kind": "string", "title": "SSID"}
FORM = {
    "prompt_id": "pform",
    "kind": "form",
    "title": "Hotspot",
    "fields": [
        {"name": "ssid", "label": "SSID", "type": "string", "max_length": 3},
        {
            "name": "channel",
            "label": "Channel",
            "type": "integer",
            "minimum": 1,
            "maximum": 11,
            "default": 6,
        },
        {
            "name": "band",
            "label": "Band",
            "type": "enum",
            "choices": [
                {"value": "2g", "label": "2.4 GHz"},
                {"value": "5g", "label": "5 GHz"},
            ],
        },
        {"name": "note", "label": "Note", "type": "string", "required": False},
    ],
}


def keys(editor, *names):
    result = None
    for name in names:
        result = editor.handle(name)
    return result


def text_of(editor):
    return "\n".join(b["text"] for b in editor.view()["blocks"])


def test_string_prompt_types_characters_and_answers_value():
    ed = PromptEditor(STRING)
    assert "[a]" in text_of(ed)
    keys(ed, "right")  # a
    keys(ed, "down", "right")  # b
    keys(ed, "up", "up", "right")  # wraps backwards from b to the last character
    assert ed.draft == "ab" + CHARS[-1]
    keys(ed, "left")  # delete
    assert keys(ed, "center") == ("answer", {"value": "ab"})


def test_string_prompt_key2_jumps_character_group():
    ed = PromptEditor(STRING)
    keys(ed, "key2", "right")  # A
    keys(ed, "key2", "right")  # 0
    assert ed.draft == "A0"
    assert ed.view()["hints"]["key2"]


def test_string_prompt_left_on_empty_text_cancels():
    assert keys(PromptEditor(STRING), "left") == ("answer", {"cancel": True})


def test_key1_sends_and_key3_cancels():
    ed = PromptEditor(STRING)
    keys(ed, "right")
    assert keys(ed, "key1") == ("answer", {"value": "a"})
    assert keys(PromptEditor(FORM), "key3") == ("answer", {"cancel": True})


def test_form_lists_fields_with_defaults_then_send_and_cancel():
    ed = PromptEditor(FORM)
    block = ed.view()["blocks"][0]
    assert [(i["label"], i.get("detail")) for i in block["items"]] == [
        ("SSID", "-"),
        ("Channel", "6"),
        ("Band", "2.4 GHz"),
        ("Note", "-"),
        ("Send", None),
        ("Cancel", None),
    ]
    assert block["selected"] == 0


def test_form_edit_each_field_type_and_send():
    ed = PromptEditor(FORM)
    keys(ed, "center", "right", "right", "center")  # ssid = "aa"
    assert ed.values["ssid"] == "aa"
    keys(ed, "down", "center", "up", "up", "center")  # channel 6 -> 8
    keys(ed, "down", "center", "down", "center")  # band -> 5g
    assert keys(ed, "key1") == (
        "answer",
        {"values": {"ssid": "aa", "channel": 8, "band": "5g"}},
    )


def test_form_integer_is_clamped_and_left_discards():
    ed = PromptEditor(FORM)
    keys(ed, "down", "center", *["up"] * 20)
    assert ed.draft == 11
    keys(ed, "left")  # discard
    assert ed.values["channel"] == 6


def test_form_string_respects_max_length():
    ed = PromptEditor(FORM)
    keys(ed, "center", "right", "right", "right", "right")
    assert ed.draft == "aaa"
    assert "At most 3" in text_of(ed)


def test_form_refuses_to_send_without_a_required_field():
    ed = PromptEditor(FORM)
    assert keys(ed, "key1") == ("redraw", {})
    assert "SSID is required" in text_of(ed)


def test_form_send_and_cancel_rows():
    ed = PromptEditor(FORM)
    keys(ed, "center", "right", "center")
    assert keys(ed, "up", "up", "center") == (
        "answer",
        {"values": {"ssid": "a", "channel": 6, "band": "2g"}},
    )
    assert keys(PromptEditor(FORM), "up", "center") == ("answer", {"cancel": True})
    assert keys(PromptEditor(FORM), "left") == ("answer", {"cancel": True})


def test_secret_string_is_masked_except_the_character_being_picked():
    ed = PromptEditor(
        {
            **FORM,
            "fields": [
                {"name": "psk", "label": "Key", "type": "string", "secret": True}
            ],
        }
    )
    keys(ed, "center", "right", "right")
    assert "aa" not in text_of(ed)
    assert "••[a]" in text_of(ed)
