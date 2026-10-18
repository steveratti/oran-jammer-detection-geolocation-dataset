# Manual handover xApp (demo)

One-shot FlexRIC xApp that sends an E2SM-RC Handover Control message.

- Copy `xapp_manual_ho.c` to `flexric/examples/xApp/c/orange/` and apply `CMakeLists.patch`.
- Build: `cd flexric/build && make xapp_manual_ho`
- Run: `HO_NODE=<e2 node idx> HO_UE=<ue id> HO_CELL=<target cell 1-9> ./xapp_manual_ho`
- The command only takes effect on the E2 node that serves the UE; try node indexes 0..N-2.
- Dashboard demo only; not part of the evaluation in the paper.
