# Dispatch

`mac-bootstrap-template` does not own the Dispatch runtime, Gate C implementation, OMP human-control adapter, or Dispatch agent skill.

Dispatch is a standalone product. Its own installer manages the global `dispatch` skill; `mac-bootstrap-template` does not register that skill in its skill registry. This repository only provides thin lifecycle targets that call an existing Dispatch checkout:

```bash
make dispatch-install
make dispatch-upgrade
make dispatch-status
make dispatch-doctor
make dispatch-uninstall
```

The default checkout is `~/.local/src/Dispatch`. Override it when developing from another local checkout:

```bash
make dispatch-doctor DISPATCH_SOURCE=/path/to/Dispatch
```

Use `dispatchctl doctor` as the product health authority. Do not add a second Dispatch runtime, gate, OMP adapter, or Dispatch skill implementation to this repository.
