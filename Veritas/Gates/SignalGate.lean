/-
  Veritas.Gates.SignalGate — Gate 1: signal / assumption consistency.

  Given a proposed trade and the market context it was formed under,
  verify that:
    1. Veritas's own policy would emit a signal in this context.
    2. The proposal direction agrees with that signal.
    3. The signal carries well-formed, non-empty assumptions.

  This gate does not know about capital or risk. Those belong to Gate 2.
-/
import Veritas.Gates.Types
import Veritas.Strategy.FundingReversion

namespace Veritas.Gates

open Veritas Veritas.Strategy

/-- Gate 1: check signal consistency.
    On approval, attaches Veritas's declared assumptions for this signal. -/
def verifySignal (p : TradeProposal) : Verdict × List Assumption :=
  let snap : MarketSnapshot :=
    ⟨p.fundingRate, p.price, p.timestamp, p.openInterest⟩
  match decide snap with
  | none =>
    (.Reject ["no_signal_under_policy"], [])
  | some s =>
    if s.direction == p.direction then
      let assumptions := extractAssumptions s
      match assumptions with
      | []      => (.Reject ["malformed_proposal_no_assumptions"], [])
      | _ :: _  => (.Approve, assumptions)
    else
      (.Reject ["direction_conflicts_with_signal"], [])

end Veritas.Gates
