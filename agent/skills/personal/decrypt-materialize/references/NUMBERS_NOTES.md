# iWork Encryption Notes

## File identification

Encrypted Apple iWork files such as Numbers can start with:

```text
%TSD-Header-###%
```

Check with `xxd file.numbers | head -1`.

## Why `numbers-parser` works

`numbers-parser` reads the Numbers container directly. On the machine that can
already open the file, that is usually enough to materialize CSV without asking
for a password again.

## Dependency

Pinned install:

```bash
pip3 install "numbers-parser==4.18.5"
```
