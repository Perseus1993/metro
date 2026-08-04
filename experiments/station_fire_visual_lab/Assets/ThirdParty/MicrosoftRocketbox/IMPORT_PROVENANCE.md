# Microsoft Rocketbox import provenance

- Source: https://github.com/microsoft/Microsoft-Rocketbox
- Commit: `0943055db6ec570bcef9f2c8b41c9e5467c808f9`
- Imported: 2026-08-02
- Scope: complete `Assets/Avatars` tree plus upstream `README.md` and `LICENSE.md`
- Base characters: 115 (`Adults`: 40, `Children`: 4, `Professions`: 71)
- Source files: 1,335
- Source bytes: 10,996,145,897
- License SHA-256: `A388BF32E3C2F6B02C30228C0896893C82AA678A00B96614A848E358C6DA3A12`

The two `Professions/Female_Party_*` directories contain facial-only duplicates.
Their usable base FBX files are present under `Adults`, so they do not increase
the 115-character base library count.

This copy belongs to the standalone visual experiment. It is presentation-only
and does not define passenger mobility, routing, age, or evacuation behavior.
