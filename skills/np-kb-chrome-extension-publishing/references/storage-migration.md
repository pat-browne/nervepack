# Migrate stored data across updates — `chrome.storage` survives upgrades

`chrome.storage.sync`/`.local` **persist across extension updates** (and Chrome
Sync carries them between machines). So when a new version changes the *shape* of
what you persist, the old shape is still sitting in users' storage on upgrade —
you must read-migrate it, or you wipe what they had. This is the MV3-specific
instance of the general rule in [[np-kb-coding-rules]] §7 ("never wipe user
data on a schema change").

- **Migrate on read, in the storage facade.** Normalize whatever is in storage
  into the current shape inside your `getSettings()` (or equivalent) every read,
  so nothing is lost even before the next write. Don't rely on a one-shot
  `onInstalled` migration — the read path is what guarantees safety.
- **Widening a field: keep the old value first.** Turning a scalar into a
  collection → wrap it as the first element, active/selected. Worked example
  (meeting-template v0.9→1.0): `template: string` → `templates: [{ name:
  'Standard', body: <the old string> }]`, that tab active. The user's text lands
  in tab #1.
- **The persisting write must not drop it.** The first `setSettings` after upgrade
  writes the new shape and removes the legacy key — assert the body survives that
  cycle, not just the first read.
- **Gate the release on an upgrade test** that seeds the *previous published
  version's* exact storage shape and asserts the content is preserved (read +
  a later save). New features never justify destroying existing users' data.
