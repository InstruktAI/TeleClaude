def manual_escape_markdown_v2(text: str) -> str:
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    # Escape each character individually
    for char in escape_chars:
        text = text.replace(char, f"\\{char}")
    return text


test_text = "Thinking about the 1.2.3 version... This-is-a-test! _Italics_ and *Bold*."
print(f"Original: {test_text}")
print(f"Escaped:  {manual_escape_markdown_v2(test_text)}")
