# B4 External images and the settings chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An image takes a file or an `https://` address, shown as a copy or from its source by a mode inherited global → quiz → question, and every module must declare its settings under that same chain.

**Architecture:** Settings first: `SettingDefinition` carries scopes, reason and labels, module manifests declare theirs, and `settings.resolve(key, quiz, question)` walks the chain. Saving an address fetches it through the media provider, so a copy normally exists and the mode only picks what `with_media_urls` shows. Checks of external addresses run from an HTMX post after an admin opens a quiz.

**Tech Stack:** Django 6.1, Jinja2, HTMX, Pico CSS, SQLite, Python standard library for fetching. No new dependency.

**Spec:** `docs/superpowers/specs/2026-11-07-b4-external-images-design.md`

## Global Constraints

- Branch `feat/b4-external-images`. Tests run in the dev container, because host uv is older than 0.13: `make test`, `make lint`, `make quality`, `make messages`.
- Layers (`tests/test_layers.py`): `domain` imports `contracts`, `kernel`, `domain`; `plugins` and `providers` import `contracts`, `kernel`, themselves. No inline scripts or styles (CSP).
- A plugin reads no settings; the API passes what it needs in `quiz_settings`.
- Admin strings in cs and en, public strings in cs, en and uk. In Czech a `QuizRun` is běh, never kolo.
- Manifests stay plain data and import no Django.
- With no question values and no addresses, an existing quiz behaves as before.
- Tests never use the network. `kvizotron-browser` keeps its data; verification there adds a new quiz.
- Limits: fetch 10 s per address, 15 MB read, 3 redirects; check 3 s per address, 10 s per request, once an hour. **[plan's call]** All fetches of one save share 25 s; what does not fit counts as a failed verification, so seven dead addresses cannot hold a request for 70 s.

## Review Focus

1. A name resolving to several addresses with one internal, an IPv4-mapped IPv6 address (`::ffff:127.0.0.1`), carrier-grade NAT (`100.64.0.1`), multicast: refused with the switch off. Task 3.
2. Revisions and attempts from before B4: images without `source`, attempts with `seed: null` and no frozen `shuffle_options`: unchanged. Tasks 2, 4.
3. A refused address on one image, with a valid file on another and alt texts filled: the form returns with the address, alt texts and the stored file. Task 4.
4. A forged POST with an unknown value in a question-level select, or a stored question value no longer offered: refused by the form, skipped by `resolve`. Task 2.
5. "Remove image" ticked with an address present: nothing is fetched and the image goes. Task 4.

---

### Task 1: Every setting declares its scopes

**Files:**
- Modify: `app/kernel/manifest.py`, all 8 `app/**/manifest.py`, `tests/fixtures/*/kvz_*/manifest.py`, `tests/support/modules.py`
- Modify: `app/domain/settings.py`, `app/domain/apps.py`, `app/api/admin_forms.py`, `app/domain/locale`, `app/api/locale`
- Test: `tests/contracts/test_settings_rule.py`, `tests/domain/test_settings.py`, `tests/kernel/test_discovery.py`

**Interfaces:**
- Produces in `app/kernel/manifest.py`: `class SettingDeclaration(BaseModel)`: `key: str`, `choices: list[str]`, `default: str`, `scopes: list[Literal["global","quiz","question"]] = ["global","quiz","question"]`, `scope_reason: str | None = None`, `label: str`, `value_labels: dict[str, str]`, `help: str | None = None`. `Manifest.settings: list[SettingDeclaration]`, required with no default.
- Produces in `app/domain/settings.py`: `SettingDefinition` gains `label`, `value_labels: Mapping[str, Any]`, `scopes: tuple[str, ...] = ALL_SCOPES`, `scope_reason: str | None = None`, `help: Any = None`. `keys_for(scope: str) -> list[str]`, `register_modules(modules: Sequence[Manifest]) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/contracts/test_settings_rule.py, over discovery.installed_modules() and CATALOGUE
def test_a_manifest_without_settings_is_refused():
    with pytest.raises(ValidationError):
        Manifest.model_validate(valid_manifest_without("settings"))

def test_a_narrower_scope_needs_a_reason():
    with pytest.raises(ValidationError):
        Manifest.model_validate(valid_manifest(settings=[declaration(scopes=["global"], scope_reason=None)]))

def test_an_unknown_scope_is_refused(): ...  # scopes=["run"] -> ValidationError

def test_every_installed_module_and_the_catalogue_follow_the_rule():
    for definition in settings.CATALOGUE.values():
        narrower = set(definition.scopes) != set(settings.ALL_SCOPES)
        assert not narrower or definition.scope_reason, definition.key

# tests/domain/test_settings.py
def test_a_duplicate_key_stops_the_start():
    with pytest.raises(StartupError):
        settings.register_modules([module_declaring(settings.COLOR_PALETTE)])

def test_keys_for_follow_the_scopes(): ...  # a global-only key is absent from keys_for("quiz")
```

- [ ] **Step 2: Run them**

Run: `make test` (with `-k` as the dev container allows). Expected: FAIL, no `settings` field.

- [ ] **Step 3: Implement**

- Validate in `SettingDeclaration`: default in choices, a value label per choice, a reason when scopes differ from the default. Every manifest gets `"settings": []`; `make_module` defaults to it.
- Move `SETTING_LABELS` and `VALUE_LABELS` from `admin_forms.py` into the definitions in `domain/settings.py`, one place for all settings. Copy their existing cs, en and uk translations from the API catalogue to the domain catalogue, then `make messages`.
- Nine existing definitions: `show_sources`, `shuffle_options`, `none_option` keep the default scopes. The other six get `("global", "quiz")` and a one-sentence reason from what each does: it applies to the attempt or the quiz as a whole.
- `register_modules`, called from `DomainConfig.ready()` with `discovery.load_modules()`, adds declarations of active modules to `CATALOGUE` and raises `StartupError` on a duplicate key.
- Forms read `settings.keys_for("global")` and `settings.keys_for("quiz")`, and take labels and `help` from the definition. Translate with `gettext` at render time, since module labels are plain msgids. `admin_quizzes.quiz_settings` loops over `keys_for("quiz")`.

- [ ] **Step 4: Run all tests**

Run: `make test`. Expected: PASS, including `test_translations`. Pages look as before: only three settings have a question scope and nothing offers it yet, so the test that it is offered comes in Task 2.

- [ ] **Step 5: Commit**

`feat: every setting declares its scopes, and every module its settings`

### Task 2: The question level

**Files:**
- Modify: `app/domain/settings.py`, `app/domain/questions.py`, `app/domain/authoring.py`, `app/domain/banks.py`, `app/domain/attempts.py`, `app/domain/revision_diff.py`
- Modify: `app/contracts/__init__.py`, `app/plugins/questions/choice/plugin.py`, `app/plugins/questions/matching/plugin.py`, `tests/fixtures/demo_site/kvz_demo_question/question.py`, `tests/contracts/question_type.py`
- Modify: `app/api/admin_forms.py`, `app/api/admin_quizzes.py`, `app/api/admin_banks.py`, `app/api/rendering.py`, `app/api/play.py`
- Test: `tests/domain/test_settings.py`, `tests/domain/test_attempts.py`, `tests/domain/test_revision_diff.py`, `tests/api/test_question_editor.py`, `tests/api/test_play.py`, `tests/contracts/test_settings_rule.py`

**Interfaces:**
- Consumes: `keys_for`, `SettingDefinition` from Task 1.
- Produces: `settings.resolve(key, quiz=None, question=None) -> str`. `settings.ALL_TYPES_QUESTION_SETTINGS = {SHOW_SOURCES}`. `QuestionTypePlugin.question_settings() -> Sequence[str]`: Výběr returns `none_option`, `shuffle_options`; Přiřazení returns nothing; Task 3 adds `external_image_mode` to Výběr. `QuestionCommonForm(..., plugin=plugin)` adds fields `setting_<key>` and a method `setting_values() -> dict[str, str]`. `apply_fields(..., setting_values: Mapping[str, str] | None = None)`, and the same keyword on `authoring.save_question` and `banks.save_question`. `question_settings(quiz, question) -> dict[str, str]` in `rendering.py`. `attempts.option_seed_for(attempt, question) -> str | None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/domain/test_settings.py
def test_question_beats_quiz_beats_global(quiz):
    question = {"settings": {"points": 1}}
    settings.set_global(SHOW_SOURCES, "off", admin_id=None)
    assert settings.resolve(SHOW_SOURCES, quiz, question) == "off"
    settings.set_override(SHOW_SOURCES, quiz, "on", admin_id=None)
    assert settings.resolve(SHOW_SOURCES, quiz, question) == "on"
    question["settings"][SHOW_SOURCES] = "off"
    assert settings.resolve(SHOW_SOURCES, quiz, question) == "off"

def test_a_question_value_no_longer_offered_is_skipped(quiz): ...  # settings[SHOW_SOURCES]="gone" -> quiz value

# tests/contracts/test_settings_rule.py
def test_each_scope_of_each_setting_is_offered_on_its_page(quiz):
    global_fields = GlobalSettingsForm().fields
    quiz_fields = QuizBehaviourForm(quiz=quiz).fields
    question_fields = set()
    for key in registry.keys("question_type"):
        form = QuestionCommonForm(plugin=registry.get("question_type", key), strategies=[], locales=["cs"])
        question_fields |= set(form.fields)
    for key, definition in settings.CATALOGUE.items():
        assert ("global" in definition.scopes) == (key in global_fields)
        assert ("quiz" in definition.scopes) == (key in quiz_fields)
        assert ("question" in definition.scopes) == (f"setting_{key}" in question_fields)

# tests/api/test_question_editor.py
def test_a_question_select_names_the_current_quiz_value(...): ...
def test_an_unknown_value_in_a_question_select_is_refused(...): ...  # 200, form error, nothing saved
def test_following_the_quiz_stores_no_value(...): ...  # question["settings"] == {"points": 1}
def test_none_option_is_not_offered_on_matching(...): ...
def test_a_bank_question_has_the_question_level_too(...): ...

# tests/domain/test_revision_diff.py
def test_a_changed_question_setting_appears_in_the_overview(...): ...  # label and value label

# tests/api/test_play.py (AC-44)
def test_sources_hidden_on_one_question_only(...): ...
def test_shuffle_on_one_question_only(...): ...  # other options keep order; reloading keeps this order
def test_none_option_set_on_one_question_only(...): ...
def test_points_and_scoring_ignore_question_settings(...): ...

# tests/domain/test_attempts.py
def test_an_attempt_from_before_b4_keeps_its_options_in_order(...): ...  # seed None, question not overridden -> None
```

- [ ] **Step 2: Run them**

Run: `make test`. Expected: FAIL, `resolve` takes no `question`.

- [ ] **Step 3: Implement**

- `resolve`: `question["settings"][key]` if offered, then the existing chain. Question values live next to `points`, stored only when set. `apply_fields` with `setting_values` drops all catalogue keys, then writes the given ones; `None` keeps them, as other fields do.
- A form field exists for a key with scope `question` and either in `ALL_TYPES_QUESTION_SETTINGS` or in `plugin.question_settings()`. First choice `""`: "Use quiz setting (now: …)", in a bank "Use global setting (now: …)". An existing question's form starts with its stored value. `_common_form`, `_save_question` and the bank's equivalents pass values through.
- `question_settings(quiz, question)` is called once per question in `play._questions`; `result_sources` resolves `SHOW_SOURCES` per question.
- Shuffling: `attempts.start` always creates a seed and freezes `"shuffle_options": flow.shuffle_options`. `option_seed_for` returns the seed when `shuffle_options` resolves on: the question value if there is one, else the frozen value, and for an attempt with no frozen value, whether it has a seed. `play._questions` passes that to `question_html`.
- `revision_diff._rows`: a `meta:setting:<key>` row for each stored value, using the definition's labels.

- [ ] **Step 4: Run all tests**

Run: `make test`. Expected: PASS. The Review Focus 2 and 4 tests are among them.

- [ ] **Step 5: Commit**

`feat: source, shuffle and none-option settings can be set per question`

### Task 3: Fetching an image from an address

**Files:**
- Create: `app/providers/media_local/remote.py`, `tests/providers/test_media_remote.py`
- Modify: `app/contracts/__init__.py`, `app/providers/media_local/provider.py`, `app/providers/media_local/manifest.py`, `app/providers/media_local/locale`, `app/plugins/questions/choice/plugin.py`, `app/api/jinja2/admin/settings.html` if it does not render `help`
- Test: `tests/providers/test_media_local.py`, `tests/domain/test_settings.py`

**Interfaces:**
- Produces in `contracts`: constants `EXTERNAL_IMAGE_MODE = "external_image_mode"`, `IMAGE_MODE_COPY = "copy"`, `IMAGE_MODE_EXTERNAL = "external"`, `ALLOW_INTERNAL_IMAGE_ADDRESSES = "allow_internal_image_addresses"`. `class ImageAddressInvalid(ImageRefused)`. `MediaStorageProvider.fetch_image(url: str, *, allow_internal: bool, deadline: float) -> str`: returns an asset id; raises `ImageAddressInvalid` or `ImageRefused`. `deadline` is `time.monotonic()` based.
- Produces in `remote.py`: `check_address(url: str) -> None` raising `RemoteRefused`; `fetch(url: str, *, allow_internal: bool, timeout: float, max_bytes: int) -> bytes` raising `RemoteRefused`; a seam `_request(url: str, ip: str, deadline: float) -> tuple[int, Mapping[str, str], bytes]` that tests replace.

- [ ] **Step 1: Write the failing tests**

```python
# tests/providers/test_media_remote.py: socket.getaddrinfo and remote._request are replaced, no network
@pytest.mark.parametrize("url", ["http://a.cz/x.png", "ftp://a.cz/x", "https://", "https://u:p@a.cz/x.png", "nonsense"])
def test_a_bad_address_is_invalid(url): ...  # check_address raises

@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1", "224.0.0.1", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1"])
def test_an_internal_address_is_refused_before_any_connection(ip, resolves_to, no_request):
    resolves_to(ip)
    with pytest.raises(RemoteRefused):
        remote.fetch("https://a.cz/x.png", allow_internal=False, timeout=1, max_bytes=10)

def test_one_internal_address_among_several_is_enough(...): ...  # ["8.8.8.8", "10.0.0.1"]
def test_the_switch_allows_an_internal_address(...): ...
def test_the_connection_goes_to_the_checked_address(...): ...  # _request received the resolved ip
def test_a_redirect_to_an_internal_address_is_refused(...): ...
def test_a_redirect_to_http_is_refused(...): ...
def test_a_fourth_redirect_is_refused(...): ...  # three pass
def test_too_many_bytes_are_refused(...): ...
def test_an_error_status_is_refused(...): ...
def test_a_passed_deadline_is_refused(...): ...

# tests/providers/test_media_local.py
def test_a_fetched_image_goes_through_the_upload_processing(...): ...  # big PNG -> stored WebP; not-an-image -> ImageRefused
def test_the_provider_declares_its_two_settings():
    assert settings.CATALOGUE[EXTERNAL_IMAGE_MODE].default == IMAGE_MODE_COPY
    assert settings.CATALOGUE[ALLOW_INTERNAL_IMAGE_ADDRESSES].default == "off"
    assert settings.CATALOGUE[ALLOW_INTERNAL_IMAGE_ADDRESSES].scopes == ("global",)
```

- [ ] **Step 2: Run them**

Run: `make test`. Expected: FAIL, no module `remote`.

- [ ] **Step 3: Implement**

- `_request` uses `http.client.HTTPSConnection`, subclassed so `connect()` opens `socket.create_connection((ip, port), timeout)` and wraps it with `ssl.create_default_context()` and `server_hostname=host`. Sends `User-Agent: Kvizotron` and no cookies.
- Internal means: not `ip.is_global`, or `is_multicast`, or `is_reserved`, after unwrapping `ipv4_mapped`. Every address `getaddrinfo` returns must pass; the first one is used. A redirect goes through the same checks with a fresh resolve.
- Manifest: `external_image_mode` with default scopes; `allow_internal_image_addresses` with `["global"]`, reason "It guards the server, not a quiz", and `help` saying any admin can turn it on, so a stolen admin account could use it to reach the internal network. Label text through a local `def _(text): return text`, so `make messages` extracts it.
- Výběr's `question_settings()` adds `EXTERNAL_IMAGE_MODE`.

- [ ] **Step 4: Run all tests**

Run: `make test`. Expected: PASS, including the "offered on its page" test, now covering the two new settings.

- [ ] **Step 5: Commit**

`feat: the media provider fetches images from an address, and never internally by default`

### Task 4: An address in the editor, and what a participant gets

**Files:**
- Modify: `app/api/admin_quizzes.py`, `app/api/admin_banks.py`, `app/api/rendering.py`, `app/settings.py`
- Modify: `app/domain/questions.py`, `app/domain/settings.py`, `app/plugins/questions/choice/plugin.py`, `app/plugins/questions/choice/jinja2/choice/{admin,public,solution}.html`
- Modify: `app/api/jinja2/admin/quiz_edit.html`, `app/api/jinja2/admin/bank.html`, `app/api/jinja2/public/privacy.html`, `docs/privacy.md`, locale files
- Test: `tests/api/test_question_editor.py`, `tests/api/test_play.py`, `tests/api/test_security_headers.py`, `tests/contracts/test_choice.py`, `tests/domain/test_settings.py`

**Interfaces:**
- Consumes: `fetch_image`, constants from Task 3; `resolve` and `setting_<key>` from Task 2.
- Produces: image shape `{"asset": str | None, "source": str (optional), "alt": {...}}`. `settings.image_mode(quiz, question) -> str`: `resolve`, or `copy` when the key is not declared because no media provider is active. `questions.images_of(definition) -> list[Mapping]`: every mapping found recursively with `alt` and `asset` or `source`. `with_media_urls(value, keep_asset=False, external=False)`. `quiz_settings` gains `"external_images": bool`, and `reveal_context` takes `quiz`. `read_question_form(request, plugin, locales, current, quiz: Quiz | None)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_question_editor.py, with storage.fetch_image replaced by a fake
def test_an_address_stores_a_copy_and_keeps_the_source(...):
    # definition["image"] == {"asset": FAKE_ID, "source": URL, "alt": {...}}
def test_an_unchanged_address_fetches_nothing(...): ...  # fake not called on the second save
def test_a_changed_address_fetches_again(...): ...
def test_an_address_without_a_copy_is_tried_again_on_each_save(...): ...
def test_a_file_beats_an_address(...): ...  # upload stored, no source, fake not called
def test_a_bad_address_is_refused_in_both_modes(...): ...  # ImageAddressInvalid -> form returned
def test_failure_in_copy_mode_returns_the_form_with_its_data(...):
    # 200; address, alt texts, and a file stored for another image are all still there; nothing saved
def test_failure_in_external_mode_saves_without_a_copy_and_marks_it(...):
    # asset None; redirect; the question row on quiz_edit shows "No copy of an image"
def test_the_mode_submitted_on_the_form_decides_at_save(...): ...  # global copy, setting_… = external -> saved
def test_a_bank_question_follows_global_when_it_fails(...): ...  # refused with global copy
def test_remove_ticked_with_an_address_fetches_nothing(...): ...
def test_the_editor_shows_the_address_and_previews_the_copy(...): ...

# tests/api/test_play.py (AC-38, AC-39)
def test_a_copy_shows_media_and_no_source_address(...):
    # page contains /media/<id>, does not contain the source address
def test_external_mode_shows_the_address_with_no_referrer(...):
    # src is the source, referrerpolicy="no-referrer"
def test_an_image_without_a_copy_shows_the_address_in_any_mode(...): ...
def test_question_beats_quiz_beats_global_for_the_image(...): ...
def test_changing_the_quiz_mode_creates_no_draft(...): ...
def test_a_solution_follows_the_same_mode(...): ...
def test_an_image_from_before_b4_still_shows(...): ...  # {"asset": id, "alt": {...}}

# tests/contracts/test_choice.py
def test_describe_definition_changes_with_the_source(...): ...
def test_public_payload_hands_the_source_only_for_the_api_to_resolve(...): ...

# tests/api/test_security_headers.py
def test_images_may_come_from_https_only(...): ...  # img-src 'self' data: https:
```

- [ ] **Step 2: Run them**

Run: `make test`. Expected: FAIL.

- [ ] **Step 3: Implement**

- `_form_with_uploads(request, quiz)` handles `<name>_source` after files. Skip when a file came or `<name>_remove` is set, clearing the source. Unchanged means a hidden `<name>_kept_source` equals it and `<name>_asset` exists. Effective mode: `setting_external_image_mode` from the form, else quiz, else global. Pass `allow_internal` from the global setting and a shared 25 s deadline.
- On `ImageAddressInvalid`: refused always. On `ImageRefused`: in `copy` refused, as a bad file, setting `<name>_refused`; in `external` keep the source with no asset. `AdminFormError` already returns the rows, so check the failed row keeps address and alts.
- Choice `_image`: an image exists with `asset` or `source`. `_public_image` passes `source` on. `_image_rows`: guard an empty asset, add a `<key>_source` row. Macro: address input `<name>_source`, hidden `<name>_kept_source`, a "no copy" note when the asset is empty. Images get `referrerpolicy="no-referrer"`.
- `with_media_urls`: `url` is the source when (`external` or no asset) and there is a source, else the route. Without `keep_asset`, both `asset` and `source` are removed, so the address never reaches a page by accident. `question_html` pops `external_images` from `quiz_settings` to pass it on; `reveal_context` resolves it itself.
- **[plan's call]** The spec's "warning on the saved page" is a chip on the question's row, in `quiz_edit.html` and `bank.html`, computed from `images_of`. It stays until fixed, and the admin UI has no one-off message system.
- `app/settings.py`: `"img-src": [CSP.SELF, "data:", "https:"]`, with a comment saying why. Privacy page and `docs/privacy.md`: a quiz may load images from another server, which then sees the participant's IP address.

- [ ] **Step 4: Run all tests, then `make messages`**

Run: `make test`. Expected: PASS, including Review Focus 3 and 5.

- [ ] **Step 5: Commit**

`feat: an image can come from an address, as a copy or from its source`

### Task 5: Publication blocks an image with no copy

**Files:**
- Modify: `app/domain/authoring.py`, `app/api/admin_quizzes.py` (problem texts near line 379), locale files
- Test: `tests/domain/test_authoring.py`, `tests/domain/test_draws.py`, `tests/api/test_admin_quizzes.py`

**Interfaces:**
- Consumes: `images_of`, `image_mode` from Task 4.
- Produces: `Problem` codes `image_no_copy` (number set) and `draw_image_no_copy` (detail is the row label).

- [ ] **Step 1: Write the failing tests**

```python
def test_copy_mode_blocks_an_image_with_no_copy(quiz): ...     # Problem(1, None, "image_no_copy")
def test_external_mode_does_not_block_it(quiz): ...
def test_a_question_value_decides_for_that_question(quiz): ...
def test_a_draw_pool_is_checked_against_this_quiz(quiz): ...   # bank external by question value stays allowed;
                                                               # no value with quiz copy -> draw_image_no_copy
def test_a_later_mode_change_leaves_a_published_quiz_playing(...): ...  # image keeps its address (AC-40)
def test_the_publish_page_names_the_question(...): ...         # 200, message, no publish button
```

- [ ] **Step 2: Run them**

Run: `make test`. Expected: FAIL.

- [ ] **Step 3: Implement**

`_question_problems` takes `quiz`; `_draw_problems` checks each row's pool with `banks.pool(row, locales)`, one problem per row. Texts say to save the question again or change the mode.

- [ ] **Step 4: Run all tests**

Run: `make test`. Expected: PASS.

- [ ] **Step 5: Commit**

`feat: publication refuses an image with no copy when the quiz shows copies`

### Task 6: The hourly check

**Files:**
- Create: `app/domain/external_images.py`, `app/api/jinja2/admin/_image_warning.html`, `app/providers/media_local/migrations/0002_address_check.py`, `tests/domain/test_external_images.py`, `tests/api/test_image_check.py`
- Modify: `app/contracts/__init__.py`, `app/providers/media_local/models.py`, `app/providers/media_local/provider.py`, `app/api/admin_quizzes.py`, `app/urls.py` or the admin URL file, `app/api/jinja2/admin/_quiz_header.html`, `app/api/jinja2/admin/publish.html`, locale files
- Test: `tests/providers/test_media_local.py`

**Interfaces:**
- Consumes: `images_of`, `image_mode`, `remote.fetch`.
- Produces in contracts: `AddressStatus(ok: bool, checked_at: datetime)`; `MediaStorageProvider.check_addresses(urls: Sequence[str], *, allow_internal: bool, per_address: float = 3.0, total: float = 10.0, max_age: timedelta = timedelta(hours=1)) -> None`; `address_status(urls: Sequence[str]) -> Mapping[str, AddressStatus]`.
- Produces in domain: `external_images.addresses_of(quiz: Quiz) -> list[str]`, sorted and distinct.
- Route: `POST /admin/quizzes/<id>/image-check`, name `admin_image_check`, returns the fragment.

- [ ] **Step 1: Write the failing tests**

```python
# tests/domain/test_external_images.py
def test_copies_are_not_listed(quiz): ...
def test_external_images_of_the_draft_and_the_published_revision_are_listed(quiz): ...
def test_an_image_with_no_copy_is_listed_in_copy_mode(quiz): ...  # it loads from its address anyway
def test_draw_pools_are_included(quiz): ...
def test_each_address_appears_once(quiz): ...

# tests/providers/test_media_local.py
def test_a_recent_check_is_not_repeated(...): ...       # second call within the hour: remote not called
def test_an_old_check_is_repeated(...): ...
def test_the_budget_leaves_the_rest_unchecked(...): ...  # clock passes total: remaining URLs stay absent
def test_an_internal_address_with_the_switch_off_counts_as_failed(...): ...

# tests/api/test_image_check.py (AC-42)
def test_an_unreachable_image_shows_a_warning(...): ...  # count and time in the fragment
def test_no_failure_means_no_warning(...): ...
def test_a_copy_mode_quiz_has_no_check_on_its_page(...): ...  # no hx-post, no provider call
def test_the_page_loads_without_running_a_check(...): ...     # GET: fake not called; header has hx-post, hx-trigger="load"
def test_the_check_needs_an_admin(...): ...                   # anonymous -> login redirect; GET -> 405
def test_the_publish_page_lists_failures_and_still_publishes(...): ...
```

- [ ] **Step 2: Run them**

Run: `make test`. Expected: FAIL.

- [ ] **Step 3: Implement**

- `addresses_of`: for each question of the draft, of its draw rows' pools, and of the latest published revision (`selection.all_questions`), take `images_of` where the image has a source and either has no asset or the mode is `external`.
- Model `AddressCheck` (`address` unique, `ok`, `checked_at`), table `media_address_check`. `check_addresses` uses `remote.fetch` with `max_bytes` 15 MB and verifies it opens as an image through the provider's existing reader, storing nothing. Any failure stores `ok=False`.
- The view runs `check_addresses(addresses_of(quiz), allow_internal=…)`, then renders `_image_warning.html` from `address_status`. The header shows a `<div hx-post hx-trigger="load" hx-swap="innerHTML">` only when `addresses_of` is non-empty, using the admin's existing HTMX CSRF pattern from `admin/base.html`. The publish view passes failed addresses to the page and adds no `Problem`.
- `_quiz_header.html` includes the warning from stored results too, so a tab opened within the hour still shows it.

- [ ] **Step 4: Run all tests**

Run: `make test`. Expected: PASS.

- [ ] **Step 5: Commit**

`feat: opening a quiz checks its external images, at most once an hour`

### Task 7: Documents and verification

**Files:**
- Create: `docs/_architecture/adr/0042-settings-inherited-and-declared.md`, `docs/_architecture/adr/0043-external-images.md`
- Modify: `docs/_architecture/adr/README.md`, `acceptance-criteria.md`, `roadmap.md`, `data-model.md`, `security.md`, `architecture.md`, `open-questions.md` if touched, `providers/media-local.md`, `plugins/question-types.md`, `modules/contracts.md`, `docs/plugin-api.md`, `CLAUDE.md`, `app/plugins/CLAUDE.md`, `app/providers/CLAUDE.md`, `app/domain/CLAUDE.md`, `TECH_DEBT.md`

- [ ] **Step 1: ADRs and rule**

ADR-0042 states the chain, the required `settings` field, the reason for a narrower scope, and how `settings` differs from `settings_requirements` (ADR-0034 stands). ADR-0043 states copy by default, the inherited mode, first verification and fetch rules, and that any admin can turn on the internal switch. In root `CLAUDE.md` under design rules, in Czech: a new setting has the scopes global, quiz and question unless a reason is stated, a module without settings declares `[]`, and whoever adds a setting decides where it fits; an agent asks the user unless the task already says.

- [ ] **Step 2: Remaining documents**

Add AC-38 to AC-44 exactly as in the spec. Mark B4 done in the roadmap with its date and update the status lines in `CLAUDE.md`. `data-model.md`: `remote_url` is replaced by `source` in the question definition, and `media_address_check` is added.

- [ ] **Step 3: Technical debt**

Run: `make tech-debt-create title="Installation modes no network / normal that derive security settings"`. Fill in the entry with the reason from the spec.

- [ ] **Step 4: Whole check**

Run: `make messages && make quality`. Expected: all pass, no untranslated strings.
Run: `make smoke`. Expected: all checks PASS. Stop the browser stack's ports only if they conflict, and never delete its data.

- [ ] **Step 5: Verify in the browser on a rebuilt `kvizotron-browser`, with a new quiz**

Desktop and 360 px, light and dark:

1. A public image address saves a copy, and the participant's page loads `/media/<id>`. Expected: fetching works from the container, so its CA certificates are present.
2. An unreachable address (`https://kvizotron-nonexistent.invalid/a.png`) in `copy` returns the form with its data; set to `external` on the question it saves, with a chip.
3. With the quiz at `copy`, publication names that question. At `external` it publishes, the participant sees the alternative text, and the quiz header warns after opening.
4. An internal address is refused with the switch off in `copy`. The switch's page shows its warning.
5. Keyboard reaches the address input and question-level selects.

- [ ] **Step 6: Commit**

`docs: milestone B4, external images and the settings chain`
