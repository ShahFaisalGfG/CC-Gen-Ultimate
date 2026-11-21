# Workflows — dev-build status

Both workflows here are **manual-trigger only** (`workflow_dispatch`) right now. The app isn't
stable/usable yet, so nothing should auto-publish a release until it is.

| Workflow | Current trigger | Trigger once stable |
|---|---|---|
| `build-release.yml` | Manual — pick an existing tag to build/release | Uncomment `push: tags: v[0-9]*` |
| `winget-release.yml` | Manual — pick a release tag to submit | Uncomment `release: types: [published]` |

To flip a workflow back to automatic, edit the commented-out `on:` block at the top of the file
(the intended trigger is already written there, just commented) and remove the
`workflow_dispatch`-only block, or keep both if you want manual + automatic triggers side by side.

Until then, `scripts/release.sh` still tags and pushes releases the normal way — you just trigger
the two workflows by hand from the **Actions** tab afterward if you want to test the pipeline.

## What `build-release.yml` checks

The workflow builds three times, once per GPU edition: `cuda` (NVIDIA GTX 10 series to RTX 50, the
main release with the plain file names that `winget-release.yml` submits), `legacy` (older NVIDIA
GPUs such as the GTX 900 series and GeForce 940MX, file names with a `_nvidia_legacy` suffix), and
`xpu` (Intel Arc and Core Ultra, file names with an `_intel_gpu` suffix). Each build installs its PyTorch and the DirectML ONNX Runtime with
`Install-GpuRuntime` from `scripts/bundle.ps1`.

Before anything is published, the `cuda` build runs the test suite and `pyright`, and every build
bundles the app with the same PyInstaller options as the local scripts (`scripts/bundle.ps1`), then
runs the bundle with `--self-test`. A missing module, DLL, data file,
speech dictionary, or QML plugin fails the workflow with a PASS/FAIL report in the log. The release
job publishes one GitHub Release with every edition's files only after all builds pass.

## Release files

Each edition publishes these files, where `<base>` is `CC-Gen-Ultimate_<version><suffix>`:

| File | What it is |
|---|---|
| `<base>_system_installer.exe`, `<base>_user_installer.exe` | The full installers. One that would reach GitHub's 2 GiB file limit is built in parts (`-1.bin`, `-2.bin`, ...) that must sit next to the exe |
| `<base>_patch_installer.exe` | The app layer only (the exe, QML, assets, licence texts). The in-app updater uses it when an installed copy's bundled runtime matches this release's (`scripts/runtime_id.py`), so most updates are tens of megabytes |
| `<base>_portable.7z` | The unpacked app, for running without installing; over the limit it becomes volumes (`.7z.001`, `.7z.002`, ...) that 7-Zip opens from the `.001` |

The release job also publishes `update.json`, written by `scripts/make_update_manifest.py` with
every edition's installers, their parts, and patch, with sizes and SHA-256 hashes, and
`update.json.sig`, its signature. The job stops before publishing if any file is 2 GiB or larger.
winget installs a single file, so `winget-release.yml` skips a release whose main installers are
split, with a warning.

## The update signing key

The app trusts an update only when `update.json.sig` verifies against a key in
`UpdateInfo.PUBLIC_KEYS` (`ccgen/config/defaults.py`), and `sign_update.py --expect` refuses to sign
with a key that list doesn't hold.

The private key lives in Doppler (project `cc-gen-ultimate`, config `prd`, secret `UPDATE_SIGNING_KEY`) and is copied from there to the repository's `UPDATE_SIGNING_KEY` Actions secret; its public half is in `UpdateInfo.PUBLIC_KEYS`. Run these in WSL, where the Doppler and GitHub CLIs are signed in:

```bash
# Copy the key from Doppler to GitHub again (after replacing it, say)
doppler secrets get UPDATE_SIGNING_KEY -p cc-gen-ultimate -c prd --plain | gh secret set UPDATE_SIGNING_KEY --repo ShahFaisalGfG/CC-Gen-Ultimate
# Print the public half, the form `UpdateInfo.PUBLIC_KEYS` holds
doppler secrets get UPDATE_SIGNING_KEY -p cc-gen-ultimate -c prd --plain | openssl ec -pubout
# Sign a local build with it
doppler run -p cc-gen-ultimate -c prd -- python3 scripts/sign_update.py release/update.json --expect ccgen/config/defaults.py
```

To replace the key, store a new one in Doppler, release one version signed with the old key whose list holds both public keys, then copy the new key to GitHub. If the key were lost, installed copies could no longer verify updates. Doppler keeps it, with its version history; never commit it or leave a copy in a file.
