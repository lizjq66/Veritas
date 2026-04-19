/-
  Veritas.Gates.Certificate — Combined verification result.

  Runs all three gates, short-circuits on rejection, and produces a
  single Certificate value that downstream callers can inspect.

  A certificate "approves" a trade iff no gate rejected. The final
  approved notional reflects any Gate 2 or Gate 3 resize.
-/
import Veritas.Gates.Types
import Veritas.Gates.SignalGate
import Veritas.Gates.ConstraintGate
import Veritas.Gates.PortfolioGate

namespace Veritas.Gates

open Veritas

/-- Run all three gates and emit a Certificate.

    Execution order is fixed: Gate 1 → Gate 2 → Gate 3.
    Each gate's size output feeds the next gate's input, so a Gate 2
    resize is visible to Gate 3. If any gate rejects, downstream gates
    receive `.Reject ["upstream_gate_rejected"]` and the final notional
    is zero. -/
def emitCertificate
    (p : TradeProposal)
    (c : AccountConstraints)
    (port : Portfolio) : Certificate :=
  let (g1, assumptions) := verifySignal p
  match g1 with
  | .Reject _ =>
    { gate1 := g1, gate2 := .Reject ["upstream_gate_rejected"],
      gate3 := .Reject ["upstream_gate_rejected"],
      assumptions := assumptions, finalNotionalUsd := 0.0 }
  | _ =>
    let g2 := checkConstraints p c
    let size2 : Float := match g2 with
      | .Approve   => p.notionalUsd
      | .Resize n  => n
      | .Reject _  => 0.0
    match g2 with
    | .Reject _ =>
      { gate1 := g1, gate2 := g2,
        gate3 := .Reject ["upstream_gate_rejected"],
        assumptions := assumptions, finalNotionalUsd := 0.0 }
    | _ =>
      let p' : TradeProposal := { p with notionalUsd := size2 }
      let g3 := checkPortfolio p' port c.equity
      let size3 : Float := match g3 with
        | .Approve   => size2
        | .Resize n  => n
        | .Reject _  => 0.0
      { gate1 := g1, gate2 := g2, gate3 := g3,
        assumptions := assumptions, finalNotionalUsd := size3 }

end Veritas.Gates
