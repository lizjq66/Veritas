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

open Veritas Veritas.Strategy

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

-- ── Soundness contract ────────────────────────────────────────────

/-- Certificate soundness: an approving certificate combines the three
    gate soundness contracts for the submitted proposal.

    If `emitCertificate p c port` returns a certificate whose
    `approves` flag is true, then:

      1. Gate 1 found the proposal signal-consistent (the strong
         statement from `verifySignal_approve_implies_consistent`).
      2. Gate 2's verdict is not a rejection, so the per-gate
         `checkConstraints_approve_within_ceiling` /
         `checkConstraints_resize_respects_ceiling` theorem applies
         to whatever non-reject verdict Gate 2 actually returned.
      3. Gate 3's verdict is not a rejection, so the per-gate
         `checkPortfolio_approve_respects_cap` theorem applies when
         Gate 3 approved.

    Numeric bounds for Gate 2 and Gate 3 are carried by their
    per-gate theorems; this certificate-level theorem composes the
    three contracts so a single reading of Certificate.lean covers
    the combined trust story. -/
theorem certificate_soundness
    (p : TradeProposal) (c : AccountConstraints) (port : Portfolio)
    (h : (emitCertificate p c port).approves = true) :
    signalConsistent p
    ∧ (emitCertificate p c port).gate2.isReject = false
    ∧ (emitCertificate p c port).gate3.isReject = false := by
  -- Case-split on verifySignal p. Only the (.Approve, _) case is
  -- consistent with an approving certificate; the rejection and
  -- (unreachable) resize branches derive a contradiction from h.
  rcases hv : verifySignal p with ⟨g1, assums⟩
  cases hg1 : g1 with
  | Reject codes =>
    exfalso
    simp [emitCertificate, hv, hg1, Certificate.approves, Verdict.isReject] at h
  | Resize n =>
    -- verifySignal never returns .Resize. Every branch of the new
    -- (v0.2) body produces .Approve or .Reject.
    exfalso
    have hv1 : (verifySignal p).1 = .Resize n := by rw [hv]; exact hg1
    unfold verifySignal at hv1
    cases hsig : firingSignals (snapshotOf p) with
    | nil => rw [hsig] at hv1; cases hv1
    | cons s rest =>
      rw [hsig] at hv1
      by_cases hmc : mutuallyConsistent (s :: rest) = true
      · simp only [hmc, if_true] at hv1
        by_cases hdir : (s.direction == p.direction) = true
        · simp only [hdir, if_true] at hv1
          cases hlist : attachedAssumptions (snapshotOf p) p.direction with
          | nil => rw [hlist] at hv1; cases hv1
          | cons x xs => rw [hlist] at hv1; cases hv1
        · simp only [hdir, if_false] at hv1; cases hv1
      · have hmcf : mutuallyConsistent (s :: rest) = false := by
          cases hval : mutuallyConsistent (s :: rest)
          · rfl
          · exact absurd hval hmc
        simp only [hmcf, if_false] at hv1; cases hv1
  | Approve =>
    -- Gate 1 approved. Apply Gate 1 theorem.
    have hApprove : (verifySignal p).1 = .Approve := by
      rw [hv]; exact hg1
    have hsigcon := verifySignal_approve_implies_consistent p hApprove
    -- Case-split on Gate 2's verdict.
    cases hg2 : checkConstraints p c with
    | Reject codes =>
      exfalso
      simp [emitCertificate, hv, hg1, hg2, Certificate.approves, Verdict.isReject] at h
    | Approve =>
      -- Case-split on Gate 3's verdict (input proposal p with notional = p.notionalUsd).
      cases hg3 : checkPortfolio { p with notionalUsd := p.notionalUsd } port c.equity with
      | Reject codes =>
        exfalso
        simp [emitCertificate, hv, hg1, hg2, hg3, Certificate.approves, Verdict.isReject] at h
      | Approve =>
        refine ⟨hsigcon, ?_, ?_⟩
        · simp [emitCertificate, hv, hg1, hg2, hg3, Verdict.isReject]
        · simp [emitCertificate, hv, hg1, hg2, hg3, Verdict.isReject]
      | Resize m =>
        refine ⟨hsigcon, ?_, ?_⟩
        · simp [emitCertificate, hv, hg1, hg2, hg3, Verdict.isReject]
        · simp [emitCertificate, hv, hg1, hg2, hg3, Verdict.isReject]
    | Resize n =>
      cases hg3 : checkPortfolio { p with notionalUsd := n } port c.equity with
      | Reject codes =>
        exfalso
        simp [emitCertificate, hv, hg1, hg2, hg3, Certificate.approves, Verdict.isReject] at h
      | Approve =>
        refine ⟨hsigcon, ?_, ?_⟩
        · simp [emitCertificate, hv, hg1, hg2, hg3, Verdict.isReject]
        · simp [emitCertificate, hv, hg1, hg2, hg3, Verdict.isReject]
      | Resize m =>
        refine ⟨hsigcon, ?_, ?_⟩
        · simp [emitCertificate, hv, hg1, hg2, hg3, Verdict.isReject]
        · simp [emitCertificate, hv, hg1, hg2, hg3, Verdict.isReject]

end Veritas.Gates
