# Personal tasks

## Recipe: Taskwarrior

License: MIT; retain upstream LICENSE. Footprint: estimated 15–60 MiB installed
disk, 10–50 MiB RAM for a small list, zero idle RAM, excluding task data.
Source builds additionally need compilers/Rust and potentially several GiB of
temporary build/cache space; disclose that separately and clean build staging.

Install: after consent, use **v3.5.0**, exact release commit
`3419d5ba1e6a780fbbb0a8d68d8fd31e675c1bf8`. Prefer a distro-provided package only
when its resolved version is exactly 3.5.0 and its package provenance is verified;
do not assume an unversioned `apt install taskwarrior` gives that pin.
Otherwise offer the pinned upstream source build below. Check available build
dependencies first (CMake >=3.24, make, C++17, libuuid on Linux, Rust >=1.91.1).
Run `cmake --version` and `rustc --version` and compare numeric versions before
configuring the build. If either is missing or older, stop and ask before
installing or replacing any toolchain; do not upgrade shared toolchains silently.
No TaskChampion sync server is installed.

In a new temporary build directory, clone the public upstream source, fetch and
check out the exact commit above detached, and verify HEAD equals that SHA.
The pinned `CMakeLists.txt` and `src/taskchampion-cpp/Cargo.toml` minimums
take precedence over INSTALL, whose Rust requirement is stale. Follow the
remaining build instructions; choose a fresh dedicated prefix, not /usr/local:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$HOME/.local/share/alans-tools/taskwarrior-3.5.0"
cmake --build build --parallel 2
cmake --install build
```

Keep LICENSE and the install manifest with the prefix; invoke its `bin/task`
directly. Existing compatible installations can be reused. Bound each build
step to 15 minutes, report progress, stop on failure, and remove temporary
source/build staging after retaining the manifest. Build time/RAM are additional
to the small runtime estimate; this is a recipe, not a prebuilt shipped binary.

Connect: no account, OAuth or password for local tasks. A Telegram user can
agree to a VM-local list directly from their phone; mobile/cloud sync is a
separate request. Set `TASKRC` to `HERMES_HOME/integrations/taskwarrior/taskrc`
and `TASKDATA` to the sibling `data` directory for the owning profile. Initialize
only these dedicated paths with directories mode 0700 and taskrc mode 0600,
using Taskwarrior's native first-run configuration privately. Confirm the profile
before adopting/importing an existing list. Do not use shared ~/.task by accident.

Verify: `task rc.confirmation=off rc.json.array=on status:pending export`.
Invoke the selected version with `TASKRC`/`TASKDATA` set to the paths above.
Success must parse as a JSON array (including an empty one). This proves local
list access, not cloud sync or reminders. Return only the requested task summary.

Use Taskwarrior for the human's persistent due dates, recurrence, tags and
priorities. Ask before destructive deletion/import or completion the user did
not request. Hermes' native cron handles agreed Telegram reminders; each job
names this profile's TASKRC/TASKDATA and verifies the list before reporting.
Taskwarrior itself sends no Telegram notifications.

Remove: pause reminders, offer a user-controlled export/backup, and remove only
the dedicated version prefix if not shared. Keep the profile task data by
default; deletion requires a separate explicit request. No credential revocation
is needed for this local-only list.

Sources: [v3.5.0 release](https://github.com/GothenburgBitFactory/taskwarrior/releases/tag/v3.5.0),
[INSTALL at release commit](https://github.com/GothenburgBitFactory/taskwarrior/blob/3419d5ba1e6a780fbbb0a8d68d8fd31e675c1bf8/INSTALL),
[CMake minimum:1](https://github.com/GothenburgBitFactory/taskwarrior/blob/3419d5ba1e6a780fbbb0a8d68d8fd31e675c1bf8/CMakeLists.txt#L1),
[Rust minimum:6](https://github.com/GothenburgBitFactory/taskwarrior/blob/3419d5ba1e6a780fbbb0a8d68d8fd31e675c1bf8/src/taskchampion-cpp/Cargo.toml#L6),
[MIT LICENSE](https://github.com/GothenburgBitFactory/taskwarrior/blob/3419d5ba1e6a780fbbb0a8d68d8fd31e675c1bf8/LICENSE).
