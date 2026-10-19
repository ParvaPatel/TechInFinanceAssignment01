# Build setup on this Mac

*Written 2026-10-13. Previous: [01-project-overview.md](01-project-overview.md).*

## Summary

- **Symptom:** every file compiled, but linking failed with `unknown architecture arm64e.x1`.
- **Cause:** this Mac's toolchain, **not the assignment code**. The compiler was using a leftover macOS 27.0 SDK that is newer than the installed linker.
- **Fix:** point the compiler at the SDK that matches the linker, then rebuild. No project files change.
- **Baseline after the fix:** 0 compiler warnings, 20 of 20 unit tests pass, 7 of 7 scenarios pass `make verify`.

## How to build (every new terminal window)

```sh
export SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk
make
make test
make verify
```

The `export` only lasts for the window it's typed in. To make it permanent, run this once:

```sh
echo 'export SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk' >> ~/.zshrc
```

After switching SDKs, run `make clean` once so nothing built against the old SDK is reused.

Don't fix this by editing the `Makefile`. The problem only exists on this machine, and the graders' machines don't have it.

## The error

```
ld: multiple errors: tapi error: malformed file
/Library/Developer/CommandLineTools/SDKs/MacOSX27.0.sdk/usr/lib/libSystem.B.tbd:4:20: error: unknown architecture
                   arm64e.x1-macos, arm64e.x1-maccatalyst ]
```

## Background: compiling vs linking

A C++ build has two steps:

1. **Compile.** Each `.cpp` file becomes a `.o` object file containing machine code. This step needs the system's *headers*.
2. **Link.** The object files are combined with system libraries (`libSystem` for the C runtime, `libc++` for the C++ standard library) into one program. This step needs to know what those libraries contain.

Both come from the **SDK** (software development kit): a folder of system headers plus a description of each system library. Those descriptions are `.tbd` ("text-based stub") files: small text files listing a library's functions and the CPU architectures it supports. The real libraries are already built into macOS, so the SDK only ships these stubs.

The linker reads the `.tbd` files. If an SDK lists an architecture the linker has never heard of, as `arm64e.x1` here, the linker refuses the file and the link fails. Every program links against `libSystem`, so *every* program fails, whatever its code.

## Proof it isn't the code

A two-line hello world, built outside the project:

| SDK used | Result |
|---|---|
| Default (27.0) | Same `unknown architecture arm64e.x1` error |
| 26.5 (`SDKROOT` set) | Links and prints `hello` |

## Diagnosis

| Check | Command | Result |
|---|---|---|
| macOS version | `sw_vers` | 26.6 (build 25G72) |
| Active toolchain | `xcode-select -p` | `/Library/Developer/CommandLineTools` (no full Xcode) |
| Command Line Tools version | `pkgutil --pkg-info=com.apple.pkg.CLTools_Executables` | 26.6, installed 2026-10-10 |
| Linker | `ld -v` | `ld-1267`. Supports `arm64` and `arm64e`, but not `arm64e.x1` |
| Installed SDKs | `ls -la /Library/Developer/CommandLineTools/SDKs/` | 15.4, 26.5 and 27.0. `MacOSX.sdk` points to **26.5** |
| SDK the compiler picks | `xcrun --show-sdk-path` | **27.0**, despite `MacOSX.sdk` pointing to 26.5 |
| Environment overrides | `echo $SDKROOT $DEVELOPER_DIR` | Neither set (before the fix) |

**Interpretation.** The tools installed on Oct 10 (version 26.6) treat 26.5 as their default SDK, and their linker matches it. The 27.0 SDK folder is dated Aug 30, so it's most likely left over from an earlier or beta install. `xcrun` picks the newest SDK it finds, so it chose 27.0, which is newer than the linker.

**Why `MacOSX.sdk` and not `MacOSX26.5.sdk`?** `MacOSX.sdk` is the default chosen by the installed Command Line Tools. When the tools are updated, it moves to an SDK that matches the new linker, so the setting keeps working.

**Longer-term options** (not needed for the assignment): remove the stale 27.0 SDK (needs `sudo`), or update the Command Line Tools once a version with a matching linker is available.

## What the build commands mean

```
c++ -I. -MMD -MP -std=c++20 -O2 -g -Wall -Wextra -Wpedantic -c app/market_maker.cpp -o build/app/market_maker.o
```

| Flag | Meaning |
|---|---|
| `-c … -o X.o` | Compile one file into an object file without linking |
| `-I.` | Look for `#include "app/…"` and `#include "sim/…"` relative to the project root |
| `-MMD -MP` | Also write a `.d` file listing which headers this file uses, so `make` rebuilds it when a header changes |
| `-std=c++20` | Use the C++20 language standard |
| `-O2` | **Optimisation level 2.** Performance numbers only mean something for optimised builds, so measure with the same flags the `Makefile` uses |
| `-g` | Include debug information. It doesn't slow the code, and it lets debuggers and profilers map machine code back to source lines |
| `-Wall -Wextra -Wpedantic` | Turn on most compiler warnings |

Then:

- `ar rcs build/libsim.a …` packs the 6 simulator objects into one *static library*.
- The three link lines build `build/market_maker` (the app objects plus `libsim.a`), `build/sim_replay` (the replay tool plus `libsim.a`) and `build/sim_tests` (the tests plus `libsim.a`).

## Baseline results (2026-10-13)

| Check | Result |
|---|---|
| `make` | All files compile with 0 warnings; all 3 programs link |
| `make test` | 20 of 20 simulator tests pass |
| `make verify` | 7 of 7 scenarios pass: basic, empty_side, gap, loss, position, quiet, sweep |

This is the reference point. Any change to `app/` must keep `make verify` at 7 of 7.

## Also: zsh and `#` comments

By default, zsh doesn't accept `#` comments typed or pasted into the terminal. A pasted line such as `export SDKROOT=… # (this terminal window only)` fails with `zsh: unknown file attribute: h`: zsh reads the comment as part of the command, and takes `(this …)` for a filename pattern. Either leave comments out of pasted commands, or turn them on permanently:

```sh
echo 'setopt interactivecomments' >> ~/.zshrc
```
