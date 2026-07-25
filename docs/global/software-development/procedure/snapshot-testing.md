---
description: 'Snapshot-testing idioms and migration patterns for string assertions in tests.'
visibility: 'public'
---

# Snapshot Testing — Procedure

## Goal

Use the three permitted test moves for string content: snapshot the emitted
string, assert a narrow non-empty guard, or compare identity through an imported
production member. Migrate literal, substring, prefix, suffix, regex, and error-message
assertions into those shapes as files are touched.

## Preconditions

- The test asserts behavior at a public boundary.
- The string is produced by the system under test, or the string value is an
  execution-significant protocol identifier.
- Snapshot diffs are read before acceptance.

## Steps

1. **Choose the permitted move.**
   - Use a snapshot for any emitted string whose content is the contract.
   - Use the non-empty guard only when accidental erasure is the bug and
     content itself is irrelevant.
   - Use an imported production member when behavior depends on token identity
     rather than prose.
2. **Snapshot at the outward-facing surface.**
   - One snapshot per surface: the full rendered message, the full CLI output,
     the full error envelope. Never snapshot internal string fragments.
   - If a test only cares about a substructure of the output, restructure the
     producer so the substructure has its own boundary, then snapshot there.
3. **Snapshot emitted content.**
   - Python uses syrupy:

     ```python
     def test_renders_session_summary(snapshot: SnapshotAssertion) -> None:
         rendered = render_session_summary(session)

         assert rendered == snapshot
     ```

   - TypeScript uses vitest:

     ```ts
     it('renders the session summary', () => {
       const rendered = renderSessionSummary(session);

       expect(rendered).toMatchInlineSnapshot();
     });
     ```

   - Keep snapshots inline by default. Use file snapshots when the captured
     output exceeds roughly 20 lines or would make the test hard to scan.

4. **Redact nondeterministic values before snapshotting.**
   - Python property-path replacement:

     ```python
     from syrupy.matchers import path_type

     def test_renders_event(snapshot: SnapshotAssertion) -> None:
         event = render_event()

         assert event == snapshot(matcher=path_type({"timestamp": (str, "TIMESTAMP")}))
     ```

   - Python callback matcher:

     ```python
     from syrupy.matchers import path_value

     def test_renders_operation(snapshot: SnapshotAssertion) -> None:
         payload = render_operation()

         assert payload == snapshot(
             matcher=path_value(
                 {"operation_id": lambda value: "OPERATION_ID" if isinstance(value, str) else value}
             )
         )
     ```

   - TypeScript asymmetric matchers:

     ```ts
     it('renders the operation envelope', () => {
       expect(renderOperation()).toMatchInlineSnapshot({
         operationId: expect.any(String),
         timestamp: expect.stringMatching(/^\d{4}-\d{2}-\d{2}T/),
       });
     });
     ```

5. **Use the canonical non-empty guard sparingly.**
   - Python:

     ```python
     def assert_non_empty_string(value: str) -> None:
         assert value


     def test_title_is_not_erased() -> None:
         assert_non_empty_string(render_title())
     ```

   - TypeScript:

     ```ts
     function expectNonEmptyString(value: string): void {
       expect(value).toBeTruthy();
     }

     it('keeps the title present', () => {
       expectNonEmptyString(renderTitle());
     });
     ```

6. **Use production members for identity.**

   Behavior that turns on an identity owned by production references the same
   production member in code and tests. A schema-level snapshot governs its
   serialized value. A test-local constant does not own production identity and
   does not repair a forbidden content assertion. Test inputs and fixture data
   that do not assert emitted string content remain inline.
   - Headers / protocol markers:

     ```python
     # production
     from enum import StrEnum

     class Header(StrEnum):
         SESSION_ID = "x-teleclaude-session-id"

     # test
     def test_uses_session_header() -> None:
         assert response.header == Header.SESSION_ID

     def test_header_schema(snapshot: SnapshotAssertion) -> None:
         assert Header.SESSION_ID.value == snapshot
     ```

     ```ts
     // production
     export const Headers = {
       sessionId: 'x-teleclaude-session-id',
     } as const;

     // test
     expect(response.header).toBe(Headers.sessionId);
     expect(Headers).toMatchInlineSnapshot();
     ```

   - Structured-error fields: same shape applies when an exception carries an
     identifier. The field name is a schema identifier, not free text.

     ```python
     # production
     class UserField(StrEnum):
         EMAIL = "email"

     raise FieldMissingError(field=UserField.EMAIL)

     # test
     with pytest.raises(FieldMissingError) as exc_info:
         validate(payload)
     assert exc_info.value.field == UserField.EMAIL
     ```

   - Production call sites use the production member, identity assertions
     import it, and a schema-level snapshot governs its serialized value.
     Review findings cite inline identifiers at production call sites, never
     fixture literals in test files.

7. **Migrate forbidden patterns.**
   - Literal equality:

     ```python
     # Before
     assert message == "ready"

     # After
     assert message == snapshot
     ```

     ```ts
     // Before
     expect(message).toBe('ready');

     // After
     expect(message).toMatchInlineSnapshot();
     ```

   - Substring:

     ```python
     # Before
     assert "ready" in message

     # After
     assert message == snapshot
     ```

     ```ts
     // Before
     expect(message).toContain('ready');

     // After
     expect(message).toMatchInlineSnapshot();
     ```

   - Prefix and suffix:

     ```python
     # Before
     assert message.startswith("session:")
     assert message.endswith("done")

     # After
     assert message == snapshot
     ```

     ```ts
     // Before
     expect(message).toStartWith('session:');
     expect(message).toEndWith('done');

     // After
     expect(message).toMatchInlineSnapshot();
     ```

   - Search methods:

     ```python
     # Before
     assert message.find("ready") >= 0
     assert message.index("session") == 0

     # After
     assert message == snapshot
     ```

   - Regex on content:

     ```python
     # Before
     assert re.search(r"session-\d+", message)

     # After
     assert normalize_ids(message) == snapshot
     ```

     ```ts
     // Before
     expect(message).toMatch(/session-\d+/);

     // After
     expect(normalizeIds(message)).toMatchInlineSnapshot();
     ```

   - Exception messages:

     ```python
     # Before
     assert exc.value.args[0] == "missing session"

     # After
     with pytest.raises(SessionNotFoundError):
         load_session("missing")
     ```

     ```ts
     // Before
     expect(error.message).toBe('missing session');

     // After
     expect(() => loadSession('missing')).toThrow(SessionNotFoundError);
     ```

   - Substring on an error message that names a schema field: this is a
     literal-on-identifier smell wearing two disguises (substring + literal).
     Fix both at once — structure the diagnostic and route the identifier
     through a production member. See step 6 for the full pattern.

     ```python
     # Before
     with pytest.raises(ValidationError) as exc:
         validate(payload)
     assert "email" in str(exc.value)

     # After
     with pytest.raises(FieldMissingError) as exc_info:
         validate(payload)
     assert exc_info.value.field == UserField.EMAIL
     ```

8. **Accept snapshot diffs deliberately.**
   - Snapshot diffs are PR review surface. Reviewers read each diff and
     confirm it matches the change's stated intent. Unreviewed snapshot
     updates are a finding.
   - Run `telec code test` first and read every snapshot diff.
   - If the diff matches the task's stated intent, rerun
     `telec code test --update-snapshots` and include the changed snapshots in
     the same commit.
   - If the diff does not match intent, fix the code. Do not update the
     snapshot.

## Outputs

- Tests use snapshots, non-empty guards, or imported production members for string content.
- Snapshot updates are committed only after the diff has been read and matched
  to the active task intent.
- Touched exempt files are migrated and removed from
  `.teleclaude/snapshot-testing-exemptions.txt`.

## Recovery

- If `telec code test` shows an unexpected snapshot diff, revert the behavior
  change through a forward fix and rerun tests without updating snapshots.
- If the lint rule flags a touched exempt file, migrate the file in the same
  change instead of adding a new exemption.
