# Conditional UCI ponder: validation and workbench compatibility

Implementation branch: `feat/uci-ponder`, fork <https://github.com/Starlight0798/jieqi>.
Validated locally on macOS arm64 with AppleClang 21, Release, native tuning.

## Engine behavior

- Advertises `Ponder` (check, default false); enabling it permits `bestmove MOVE ponder REPLY`.
- `go ponder` starts from the GUI's projected position after the predicted opponent reply.
- `ponderhit` retains the running search and starts charging its move clock at the hit.
  This applies to wall time and `NodesTime`; `info` retains total search effort.
- A completed depth/node-limited search or terminal root holds its result until hit/stop.
- `stop` releases the waiting result; the GUI must drain it before starting a replacement.
- A prediction requires a legal two-move PV with determinate observations. Face-up movers and
  face-down movers whose urn contains one possible identity type are supported. Several copies
  of that same type are sufficient. PVs now continue through those singleton chance nodes.
- An ambiguous reveal by our mover or the opponent suppresses the prediction. Our capture of an
  unknown face-down victim also suppresses it because we observe that victim's identity.
  Opponent captures of our face-down pieces leave our urn unchanged and can be predicted.
- Predictions are four coordinates. A GUI projecting a singleton dark move must infer and record
  its reveal suffix when preparing the position/history. It must check authoritative observations.
- No separate prediction search is performed after an ambiguous observation by our move.

## Validation

`cmake --build engine/build -j4` and `ctest --test-dir engine/build --output-on-failure` pass:

- C++ policy/PV checks cover known and singleton movers, multiple copies of a single identity,
  uncertain movers, both capture observation cases, illegal/missing PVs, and a NodesTime hit
  that preserves at least 1,000 nodes of fresh post-hit budget.
- Ten Python real-process UCI tests cover option/prediction output, completed depth/node limits,
  terminal positions, `isready`, idle hit, immediate hit/stop with one and two threads, stop then
  replacement, wall-clock accounting/search reuse, NodesTime/native clocks, command keyword
  ordering after `searchmoves`, and quit during ponder.
- `engine/build/jqe_difftest 1000 1`: 198,249 positions, 2,983,428 moves checked, zero failures;
  962 repetition cycles checked, zero failures.
- Start-position perft depths 1/2/3: **44 / 1,926 / 83,907**.
- With `engine/nets/it014.jqn`, local bench is **34,130 nodes** both before and after the feature.
  All six individual node counts, chosen moves, and scores match. The comparison baseline is
  the original commit with only the same two Apple Silicon build fixes applied. The repository's
  documented 45,315 signature does not reproduce on this host, even without the feature.

## qqchess-jq-workbench

No workbench files were changed. Its existing `electron-app/pikafish-bridge.js`,
`electron-app/jieqi-ponder.js`, `electron-app/ponder-session.js` and
`electron-app/ponder-preview.js` were exercised together with the real new JQE executable.
An in-memory integration script passed 42 assertions, including capability discovery,
prediction parsing, candidate confirmation, preview rendering, a hit and a miss.

Actual wire sequence (engine coordinates):

```text
> setoption name Ponder value true
> position fen r3k4/9/9/9/4P4/9/9/9/9/R3K4 w - 0 1
> go depth 3 searchmoves a0a1
< bestmove a0a1 ponder a9a1
> position fen r3k4/9/9/9/4P4/9/9/9/9/R3K4 w - 0 1 moves a0a1 a9a1
> go ponder depth 3
  [depth 3 reached; no bestmove during another 200 ms]
> ponderhit
< bestmove e5e6 ponder a1a0
```

On a miss the observed order was `stop`, old `bestmove`, replacement `position`, replacement
`go`; the old request was marked interrupted. Workbench coordinates reverse the UCI ranks;
its API search move `a9a8` produced engine move `a0a1` above.

The existing focused suite also passes, **22 tests / zero failures**:

```sh
node --test tests/jieqi-ponder.test.js tests/jieqi-jqe-protocol.test.js tests/jieqi-ponder-preview.test.js
```

Current limitations:

- Ordinary face-up predictions work through the existing bridge/session/candidate/preview path.
- Candidate confirmation rejects covered sources and targets, including singleton dark movers and
  opponent captures of our dark piece. Preview has a separate equivalent guard. Both need updating.
- Singleton integration must infer the reveal suffix, project the correct urn updates, and compare
  the full resulting board, pools, side, game/ply, and observed history on a hit. Coordinate equality
  alone is insufficient. Existing history-sensitive session matching should be retained.
- The workbench may stop/restart when hit limits differ from ponder limits. Bare UCI `ponderhit`
  cannot replace clocks supplied by the original `go ponder`; host timers still matter.
- The older broader `tests/ponder.test.js` has 20 preexisting failures from removed candidate APIs
  and clock mocks. These were observed separately; they are not introduced or fixed here.
- Validation did not exercise live server submissions, the running Electron UI, or production
  clock-policy performance.
