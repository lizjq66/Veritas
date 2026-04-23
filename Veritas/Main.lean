/-
  Veritas.Main — CLI entry point for the Lean verification kernel.

  v0.2 Slice 5: all decision-path values flow as exact `Rat`.
  The CLI parses decimal strings directly into `Rat` via
  `strToRat!`; outputs are emitted through `ratToFloat` at the
  JSON boundary.
-/
import Lean.Data.Json.Parser
import Veritas.Types
import Veritas.Finance.PositionSizing
import Veritas.Strategy.FundingReversion
import Veritas.Strategy.BasisReversion
import Veritas.Strategy.ExitLogic
import Veritas.Strategy.Regime
import Veritas.Learning.Reliability
import Veritas.Finance.ExecutionQuality
import Veritas.Gates.Types
import Veritas.Gates.SignalGate
import Veritas.Gates.ConstraintGate
import Veritas.Gates.PortfolioGate
import Veritas.Gates.Certificate

open Veritas

-- ── String → Rat parser ─────────────────────────────────────────

/-- Parse a numeric string to an exact `Rat` via Lean's JSON number
    parser. `"0.0012"` becomes `12/10000`, etc. -/
private def strToRat! (s : String) : Rat :=
  match Lean.Json.parse s with
  | .ok (.num n) =>
    -- JsonNumber: mantissa × 10^(−exponent). Build exactly in Rat.
    let numerator : Int := n.mantissa
    let denominator : Nat := 10 ^ n.exponent
    Rat.divInt numerator (Int.ofNat denominator)
  | _ => panic! s!"strToRat!: cannot parse '{s}'"

/-- For JSON output. -/
private def ratToFloat (r : Rat) : Float := Learning.ratToFloat r

/-- v0.4 migration shim: translate a legacy `(reliability, sampleSize)`
    pair — what the Python bridge still sends — into the
    `(successes, failures)` pair Gate 2's Bayesian sizer now expects.
    Uniform `Beta(1, 1)` prior. Floor semantics on `reliability ×
    sampleSize`; saturates at 0 on negative reliability.

    To be removed in slice 5 once the Python bridge sends
    `(successes, failures, priorAlpha, priorBeta)` directly. -/
private def legacyRelToBeta (rel : Rat) (sample : Nat) : Nat × Nat :=
  let prod : Rat := rel * (sample : Rat)
  let successes : Nat := prod.num.toNat / prod.den
  let failures : Nat := sample - successes
  (successes, failures)

-- ── JSON output helpers ───────────────────────────────────────────

private def jsonStr (k v : String) : String := s!"\"{k}\": \"{v}\""
private def jsonNum (k : String) (v : Rat) : String := s!"\"{k}\": {ratToFloat v}"
private def jsonNumFloat (k : String) (v : Float) : String := s!"\"{k}\": {v}"
private def jsonNat (k : String) (v : Nat) : String := s!"\"{k}\": {v}"
private def jsonObj (fields : List String) : String :=
  "{ " ++ ", ".intercalate fields ++ " }"

private def jsonCodes (codes : List String) : String :=
  let quoted := codes.map (fun c => s!"\"{c}\"")
  "[" ++ ", ".intercalate quoted ++ "]"

private def jsonAssumptions (xs : List Assumption) : String :=
  let items := xs.map fun a =>
    jsonObj [jsonStr "name" a.name, jsonStr "description" a.description]
  "[" ++ ", ".intercalate items ++ "]"

private def jsonVerdict (v : Gates.Verdict) : String :=
  match v with
  | .Approve =>
    jsonObj [jsonStr "verdict" "approve"]
  | .Resize n =>
    jsonObj [jsonStr "verdict" "resize", jsonNum "new_notional_usd" n]
  | .Reject codes =>
    jsonObj [jsonStr "verdict" "reject",
             s!"\"reason_codes\": {jsonCodes codes}"]

-- ── Primitive command handlers ────────────────────────────────────

private def handleDecide (args : List String) : IO UInt32 := do
  let (frS, priceS, tsS, oiS) ← match args with
    | [a, b, c]    => pure (a, b, c, "0")
    | [a, b, c, d] => pure (a, b, c, d)
    | _ => IO.eprintln "usage: veritas-core decide <fr> <price> <ts> [oi]"; return 1
  let snapshot : MarketSnapshot :=
    ⟨strToRat! frS, strToRat! priceS, tsS.toNat!, strToRat! oiS, 0, 0⟩
  match Strategy.decide snapshot with
  | some signal =>
    IO.println (jsonObj [jsonStr "action" "signal",
                         jsonStr "direction" signal.direction.toString,
                         jsonNum "funding_rate" signal.fundingRate,
                         jsonNum "price" signal.price])
  | none =>
    IO.println "null"
  return 0

private def handleDecideBasis (args : List String) : IO UInt32 := do
  match args with
  | [perpS, spotS, tsS] =>
    let snapshot : MarketSnapshot :=
      ⟨0, strToRat! perpS, tsS.toNat!, 0, strToRat! spotS, 0⟩
    match Strategy.decideBasis snapshot with
    | some signal =>
      IO.println (jsonObj [jsonStr "action" "signal",
                           jsonStr "strategy" "basis_reversion",
                           jsonStr "direction" signal.direction.toString,
                           jsonNum "perp_price" signal.price,
                           jsonNum "spot_price" (strToRat! spotS)])
      return 0
    | none =>
      IO.println "null"; return 0
  | _ =>
    IO.eprintln "usage: veritas-core decide-basis <perp_price> <spot_price> <timestamp>"
    return 1

private def handleExtractBasis (args : List String) : IO UInt32 := do
  match args with
  | [dirS, perpS] =>
    match Direction.fromString? dirS with
    | none => IO.eprintln s!"unknown direction: {dirS}"; return 1
    | some dir =>
      let signal : Signal := ⟨dir, 0, strToRat! perpS⟩
      let assumptions := Strategy.extractBasisAssumptions signal
      IO.println (jsonAssumptions assumptions)
      return 0
  | _ =>
    IO.eprintln "usage: veritas-core extract-basis <direction> <perp_price>"
    return 1

private def handleExtract (args : List String) : IO UInt32 := do
  match args with
  | [dirS, frS, priceS] =>
    match Direction.fromString? dirS with
    | none => IO.eprintln s!"unknown direction: {dirS}"; return 1
    | some dir =>
      let signal : Signal := ⟨dir, strToRat! frS, strToRat! priceS⟩
      let assumptions := Strategy.extractAssumptions signal
      IO.println (jsonAssumptions assumptions)
      return 0
  | _ =>
    IO.eprintln "usage: veritas-core extract <direction> <fr> <price>"
    return 1

private def handleSize (args : List String) : IO UInt32 := do
  match args with
  | [equityS, relS, sampleS] =>
    let eq := strToRat! equityS
    let rel := strToRat! relS
    let sample := sampleS.toNat!
    -- v0.4 shim: translate legacy (rel, sample) to a Beta(1,1)-prior
    -- posterior; retire when bridge sends raw (successes, failures).
    let (succ, fail) := legacyRelToBeta rel sample
    let posterior : Learning.BetaPosterior :=
      { successes := succ, failures := fail, priorAlpha := 1, priorBeta := 1 }
    let size := Finance.calculatePositionSizeFromPosterior eq posterior
    IO.println (jsonObj [jsonNum "position_size" size,
                         jsonNum "equity" eq,
                         jsonNum "reliability" rel])
    return 0
  | _ =>
    IO.eprintln "usage: veritas-core size <equity> <reliability> <sample_size>"
    return 1

private def handleMonitor (args : List String) : IO UInt32 := do
  match args with
  | [frS, priceS, tsS, oiS, dirS, epS, szS, levS, slS, etsS, aname] =>
    match Direction.fromString? dirS with
    | none => IO.eprintln s!"unknown direction: {dirS}"; return 1
    | some dir =>
      let snapshot : MarketSnapshot :=
        ⟨strToRat! frS, strToRat! priceS, tsS.toNat!, strToRat! oiS, 0, 0⟩
      let position : Position :=
        ⟨dir, strToRat! epS, strToRat! szS, strToRat! levS,
         strToRat! slS, etsS.toNat!, aname, "", 0⟩
      let decision := Strategy.checkExit snapshot position
      if decision.shouldExit then
        let reasonStr := match decision.reason with
          | some r => r.toString
          | none   => "unknown"
        IO.println (jsonObj [jsonStr "action" "exit", jsonStr "reason" reasonStr])
      else
        IO.println (jsonObj [jsonStr "action" "hold"])
      return 0
  | _ =>
    IO.eprintln "usage: veritas-core monitor <fr> <price> <ts> <oi> <dir> <ep> <sz> <lev> <sl> <ets> <aname>"
    return 1

private partial def parseReliabilityPairs
    : List String → Option (List Learning.ReliabilityStats)
  | []              => some []
  | _ :: []         => none
  | w :: t :: rest  =>
    match Learning.ReliabilityStats.mk? w.toNat! t.toNat! with
    | none        => none
    | some stats  =>
      match parseReliabilityPairs rest with
      | some tail => some (stats :: tail)
      | none      => none

private def handleAggregateReliability (args : List String) : IO UInt32 := do
  match args with
  | _nStr :: pairs =>
    match parseReliabilityPairs pairs with
    | none =>
      IO.eprintln "usage: veritas-core aggregate-reliability <n_pairs> <wins_1> <total_1> ..."
      return 1
    | some statsList =>
      let (rel, sz) := Learning.aggregateReliability statsList
      IO.println (jsonObj [
        jsonNum "reliability" rel,
        jsonNat "sample_size" sz])
      return 0
  | [] =>
    IO.eprintln "usage: veritas-core aggregate-reliability <n_pairs> <wins_1> <total_1> ..."
    return 1

private def handleUpdateReliability (args : List String) : IO UInt32 := do
  match args with
  | [winsS, totalS, reasonS] =>
    match ExitReason.fromString? reasonS with
    | none => IO.eprintln s!"unknown exit reason: {reasonS}"; return 1
    | some reason =>
      match Learning.ReliabilityStats.mk? winsS.toNat! totalS.toNat! with
      | none => IO.eprintln "invalid stats: wins must be ≤ total"; return 1
      | some stats =>
      let newStats := Learning.updateReliability stats reason
      let score := Learning.reliabilityScore newStats
      IO.println (jsonObj [jsonNat "wins" newStats.wins,
                           jsonNat "total" newStats.total,
                           jsonNum "reliability" score])
      return 0
  | _ =>
    IO.eprintln "usage: veritas-core update-reliability <wins> <total> <exit_reason>"
    return 1

private def handleClassifyRegime (args : List String) : IO UInt32 := do
  match args with
  | [priceChangeS] =>
    let pc := strToRat! priceChangeS
    let regime := Strategy.classifyRegime pc
    IO.println (jsonObj [jsonStr "regime" regime.toString])
    return 0
  | _ =>
    IO.eprintln "usage: veritas-core classify-regime <price_change_24h>"
    return 1

private def handleBuildContext (args : List String) : IO UInt32 := do
  match args with
  | [frS, priceS, oiS, volS, premS, spreadS, prevS] =>
    let price := strToRat! priceS
    let prev := strToRat! prevS
    let pc := Strategy.priceChange24h price prev
    let regime := Strategy.classifyRegime pc
    IO.println (jsonObj [
      jsonNum "funding_rate" (strToRat! frS),
      jsonNum "asset_price" price,
      jsonNum "open_interest" (strToRat! oiS),
      jsonNum "volume_24h" (strToRat! volS),
      jsonNum "premium" (strToRat! premS),
      jsonNum "price_change_24h" pc,
      jsonNum "spread_bps" (strToRat! spreadS),
      jsonStr "regime_tag" regime.toString])
    return 0
  | _ =>
    IO.eprintln "usage: veritas-core build-context <fr> <price> <oi> <vol> <prem> <spread> <prev_price>"
    return 1

private def handleJudgeSignal (args : List String) : IO UInt32 := do
  match args with
  | [reasonS] =>
    match ExitReason.fromString? reasonS with
    | none => IO.eprintln s!"unknown exit reason: {reasonS}"; return 1
    | some reason =>
      let correct := Finance.signalCorrect reason
      IO.println (jsonObj [jsonStr "signal_correct" (if correct then "true" else "false")])
      return 0
  | _ =>
    IO.eprintln "usage: veritas-core judge-signal <exit_reason>"
    return 1

private def handleExecutionQuality (args : List String) : IO UInt32 := do
  match args with
  | [markS, fillS, exitS, expectedS, realizedS] =>
    let mark := strToRat! markS
    let fill := strToRat! fillS
    let exit := strToRat! exitS
    let expected := strToRat! expectedS
    let realized := strToRat! realizedS
    IO.println (jsonObj [
      jsonNum "slippage_bps" (Finance.slippageBps mark fill),
      jsonNum "price_impact_bps" (Finance.priceImpactBps mark exit),
      jsonNum "realized_vs_expected_pnl" (Finance.realizedVsExpectedPnl realized expected)])
    return 0
  | _ =>
    IO.eprintln "usage: veritas-core execution-quality <mark> <fill> <exit> <expected_pnl> <realized_pnl>"
    return 1

-- ── Gate command handlers ────────────────────────────────────────

private def handleVerifySignal (args : List String) : IO UInt32 := do
  let parse := fun (dirS notionalS frS priceS tsS oiS spotS liqS : String) => do
    match Direction.fromString? dirS with
    | none => IO.eprintln s!"unknown direction: {dirS}"; return (1 : UInt32)
    | some dir =>
      let proposal : Gates.TradeProposal :=
        ⟨dir, strToRat! notionalS, strToRat! frS, strToRat! priceS,
         tsS.toNat!, strToRat! oiS, strToRat! spotS, strToRat! liqS, "", 0⟩
      let (verdict, assumptions) := Gates.verifySignal proposal
      IO.println (jsonObj [
        jsonStr "gate" "1",
        jsonStr "name" "signal_consistency",
        s!"\"result\": {jsonVerdict verdict}",
        s!"\"assumptions\": {jsonAssumptions assumptions}"])
      return 0
  match args with
  | [dirS, frS, priceS, tsS, oiS, notionalS, spotS, liqS] =>
    parse dirS notionalS frS priceS tsS oiS spotS liqS
  | [dirS, frS, priceS, tsS, oiS, notionalS, spotS] =>
    parse dirS notionalS frS priceS tsS oiS spotS "0"
  | [dirS, frS, priceS, tsS, oiS, notionalS] =>
    parse dirS notionalS frS priceS tsS oiS "0" "0"
  | _ =>
    IO.eprintln "usage: veritas-core verify-signal <dir> <fr> <price> <ts> <oi> <notional> [spot_price] [liquidations24h]"
    return 1

private def handleCheckConstraints (args : List String) : IO UInt32 := do
  match args with
  | [dirS, notionalS, equityS, relS, sampleS, maxLevS, maxFracS, stopPctS] =>
    match Direction.fromString? dirS with
    | none => IO.eprintln s!"unknown direction: {dirS}"; return 1
    | some dir =>
      let proposal : Gates.TradeProposal :=
        ⟨dir, strToRat! notionalS, 0, 0, 0, 0, 0, 0, "", 0⟩
      let (succ, fail) := legacyRelToBeta (strToRat! relS) sampleS.toNat!
      let constraints : Gates.AccountConstraints :=
        ⟨strToRat! equityS, strToRat! maxFracS, strToRat! maxLevS,
         strToRat! stopPctS, succ, fail, 1, 1, 0⟩
      let verdict := Gates.checkConstraints proposal constraints
      IO.println (jsonObj [
        jsonStr "gate" "2",
        jsonStr "name" "strategy_constraint_compatibility",
        s!"\"result\": {jsonVerdict verdict}"])
      return 0
  | _ =>
    IO.eprintln "usage: veritas-core check-constraints <dir> <notional> <equity> <reliability> <sample_size> <max_leverage> <max_pos_frac> <stop_pct>"
    return 1

private partial def parseCorrelationTriples
    : List String → Option (List Gates.CorrelationEntry)
  | []                      => some []
  | a :: b :: c :: rest     =>
    match parseCorrelationTriples rest with
    | some tail => some (⟨a, b, strToRat! c⟩ :: tail)
    | none      => none
  | _                       => none

private def handleCheckPortfolio (args : List String) : IO UInt32 := do
  match args with
  | [dirS, notionalS, equityS, maxFracS, "none"] =>
    match Direction.fromString? dirS with
    | none => IO.eprintln s!"unknown direction: {dirS}"; return 1
    | some dir =>
      let proposal : Gates.TradeProposal :=
        ⟨dir, strToRat! notionalS, 0, 0, 0, 0, 0, 0, "", 0⟩
      let port : Gates.Portfolio := ⟨[], strToRat! maxFracS, []⟩
      let verdict := Gates.checkPortfolio proposal port ⟨strToRat! equityS, 0, 0, 0, 0, 0, 1, 1, 0⟩
      IO.println (jsonObj [
        jsonStr "gate" "3",
        jsonStr "name" "portfolio_interference",
        s!"\"result\": {jsonVerdict verdict}"])
      return 0
  | [dirS, notionalS, equityS, maxFracS, "one", exDirS, exEpS, exSzS] =>
    match Direction.fromString? dirS, Direction.fromString? exDirS with
    | some dir, some exDir =>
      let proposal : Gates.TradeProposal :=
        ⟨dir, strToRat! notionalS, 0, 0, 0, 0, 0, 0, "", 0⟩
      let pos : Position :=
        ⟨exDir, strToRat! exEpS, strToRat! exSzS, 1, 5, 0, "", "", 0⟩
      let port : Gates.Portfolio := ⟨[pos], strToRat! maxFracS, []⟩
      let verdict := Gates.checkPortfolio proposal port ⟨strToRat! equityS, 0, 0, 0, 0, 0, 1, 1, 0⟩
      IO.println (jsonObj [
        jsonStr "gate" "3",
        jsonStr "name" "portfolio_interference",
        s!"\"result\": {jsonVerdict verdict}"])
      return 0
    | _, _ =>
      IO.eprintln s!"unknown direction in check-portfolio"; return 1
  | _ =>
    IO.eprintln "usage: veritas-core check-portfolio <dir> <notional> <equity> <max_gross_frac> (none | one <exist_dir> <exist_ep> <exist_sz>)"
    return 1

private def handleClassifyExit (args : List String) : IO UInt32 :=
  handleMonitor args

private def handleCheckPortfolioEx (args : List String) : IO UInt32 := do
  let usage :=
    "usage: veritas-core check-portfolio-ex <dir> <notional> <equity> " ++
    "<daily_var_limit> <max_gross_frac> <prop_asset> <prop_vol> " ++
    "(none | one <ed> <ep> <sz> <asset> <vol>) <n_corr> [<a> <b> <c>]*"
  match args with
  | dirS :: notionalS :: equityS :: varLimS :: maxFracS :: propAssetS
      :: propVolS :: "none" :: _nCorrS :: corrArgs =>
    match Direction.fromString? dirS, parseCorrelationTriples corrArgs with
    | some dir, some corrs =>
      let proposal : Gates.TradeProposal :=
        ⟨dir, strToRat! notionalS, 0, 0, 0, 0, 0, 0, propAssetS,
         strToRat! propVolS⟩
      let port : Gates.Portfolio := ⟨[], strToRat! maxFracS, corrs⟩
      let constraints : Gates.AccountConstraints :=
        ⟨strToRat! equityS, 0, 0, 0, 0, 0, 1, 1, strToRat! varLimS⟩
      let verdict := Gates.checkPortfolio proposal port constraints
      IO.println (jsonObj [
        jsonStr "gate" "3",
        jsonStr "name" "portfolio_interference",
        s!"\"result\": {jsonVerdict verdict}"])
      return 0
    | _, _ => IO.eprintln usage; return 1
  | dirS :: notionalS :: equityS :: varLimS :: maxFracS :: propAssetS
      :: propVolS :: "one" :: exDirS :: exEpS :: exSzS :: exAssetS
      :: exVolS :: _nCorrS :: corrArgs =>
    match Direction.fromString? dirS,
          Direction.fromString? exDirS,
          parseCorrelationTriples corrArgs with
    | some dir, some exDir, some corrs =>
      let proposal : Gates.TradeProposal :=
        ⟨dir, strToRat! notionalS, 0, 0, 0, 0, 0, 0, propAssetS,
         strToRat! propVolS⟩
      let pos : Position :=
        ⟨exDir, strToRat! exEpS, strToRat! exSzS, 1, 5, 0, "", exAssetS,
         strToRat! exVolS⟩
      let port : Gates.Portfolio := ⟨[pos], strToRat! maxFracS, corrs⟩
      let constraints : Gates.AccountConstraints :=
        ⟨strToRat! equityS, 0, 0, 0, 0, 0, 1, 1, strToRat! varLimS⟩
      let verdict := Gates.checkPortfolio proposal port constraints
      IO.println (jsonObj [
        jsonStr "gate" "3",
        jsonStr "name" "portfolio_interference",
        s!"\"result\": {jsonVerdict verdict}"])
      return 0
    | _, _, _ => IO.eprintln usage; return 1
  | _ => IO.eprintln usage; return 1

private def handleEmitCertificateEx (args : List String) : IO UInt32 := do
  let usage :=
    "usage: veritas-core emit-certificate-ex <dir> <notional> <fr> " ++
    "<price> <ts> <oi> <spot> <equity> <daily_var_limit> <rel> <sample> " ++
    "<max_lev> <max_pos_frac> <stop_pct> <max_gross_frac> <prop_asset> " ++
    "<prop_vol> (none | one <ed> <ep> <sz> <asset> <vol>) " ++
    "<n_corr> [<a> <b> <c>]*"
  let buildAndEmit := fun (port : Gates.Portfolio)
                          (dirStr : String) (notionalStr frStr priceStr : String)
                          (tsStr oiStr spotStr : String)
                          (equityStr varLimStr relStr sampleStr : String)
                          (maxLevStr maxFracStr stopPctStr : String)
                          (propAsset propVolStr : String) => do
    match Direction.fromString? dirStr with
    | none => IO.eprintln s!"unknown direction: {dirStr}"; return (1 : UInt32)
    | some dir =>
      let proposal : Gates.TradeProposal :=
        ⟨dir, strToRat! notionalStr, strToRat! frStr, strToRat! priceStr,
         tsStr.toNat!, strToRat! oiStr, strToRat! spotStr, 0, propAsset,
         strToRat! propVolStr⟩
      let (succ, fail) := legacyRelToBeta (strToRat! relStr) sampleStr.toNat!
      let constraints : Gates.AccountConstraints :=
        ⟨strToRat! equityStr, strToRat! maxFracStr, strToRat! maxLevStr,
         strToRat! stopPctStr, succ, fail, 1, 1, strToRat! varLimStr⟩
      let cert := Gates.emitCertificate proposal constraints port
      IO.println (jsonObj [
        s!"\"gate1\": {jsonVerdict cert.gate1}",
        s!"\"gate2\": {jsonVerdict cert.gate2}",
        s!"\"gate3\": {jsonVerdict cert.gate3}",
        s!"\"assumptions\": {jsonAssumptions cert.assumptions}",
        jsonNum "final_notional_usd" cert.finalNotionalUsd,
        jsonStr "approves" (if cert.approves then "true" else "false")])
      return 0
  match args with
  | d :: n :: fr :: pr :: ts :: oi :: sp
      :: eq :: varLim :: rel :: sam :: lev :: pfrac :: stop
      :: gfrac :: propAsset :: propVol :: "none" :: _nCorrS :: corrArgs =>
    match parseCorrelationTriples corrArgs with
    | some corrs =>
      let port : Gates.Portfolio := ⟨[], strToRat! gfrac, corrs⟩
      buildAndEmit port d n fr pr ts oi sp eq varLim rel sam lev pfrac stop
                   propAsset propVol
    | none => IO.eprintln usage; return 1
  | d :: n :: fr :: pr :: ts :: oi :: sp
      :: eq :: varLim :: rel :: sam :: lev :: pfrac :: stop
      :: gfrac :: propAsset :: propVol
      :: "one" :: exDirS :: exEpS :: exSzS :: exAssetS :: exVolS
      :: _nCorrS :: corrArgs =>
    match Direction.fromString? exDirS, parseCorrelationTriples corrArgs with
    | some exDir, some corrs =>
      let pos : Position :=
        ⟨exDir, strToRat! exEpS, strToRat! exSzS, 1, 5, 0, "", exAssetS,
         strToRat! exVolS⟩
      let port : Gates.Portfolio := ⟨[pos], strToRat! gfrac, corrs⟩
      buildAndEmit port d n fr pr ts oi sp eq varLim rel sam lev pfrac stop
                   propAsset propVol
    | _, _ => IO.eprintln usage; return 1
  | _ => IO.eprintln usage; return 1

private def handleEmitCertificate (args : List String) : IO UInt32 := do
  let parse := fun (port : Gates.Portfolio)
                   (dirStr : String) (notionalStr frStr priceStr : String)
                   (tsStr oiStr spotStr : String)
                   (equityStr relStr sampleStr : String)
                   (maxLevStr maxFracStr stopPctStr : String) => do
    match Direction.fromString? dirStr with
    | none => IO.eprintln s!"unknown direction: {dirStr}"; return (1 : UInt32)
    | some dir =>
      let proposal : Gates.TradeProposal :=
        ⟨dir, strToRat! notionalStr, strToRat! frStr, strToRat! priceStr,
         tsStr.toNat!, strToRat! oiStr, strToRat! spotStr, 0, "", 0⟩
      let (succ, fail) := legacyRelToBeta (strToRat! relStr) sampleStr.toNat!
      let constraints : Gates.AccountConstraints :=
        ⟨strToRat! equityStr, strToRat! maxFracStr, strToRat! maxLevStr,
         strToRat! stopPctStr, succ, fail, 1, 1, 0⟩
      let cert := Gates.emitCertificate proposal constraints port
      IO.println (jsonObj [
        s!"\"gate1\": {jsonVerdict cert.gate1}",
        s!"\"gate2\": {jsonVerdict cert.gate2}",
        s!"\"gate3\": {jsonVerdict cert.gate3}",
        s!"\"assumptions\": {jsonAssumptions cert.assumptions}",
        jsonNum "final_notional_usd" cert.finalNotionalUsd,
        jsonStr "approves" (if cert.approves then "true" else "false")])
      return 0
  match args with
  | [d, n, fr, pr, ts, oi, sp, eq, rel, sam, lev, pfrac, stop, gfrac, "none"] =>
    parse ⟨[], strToRat! gfrac, []⟩ d n fr pr ts oi sp eq rel sam lev pfrac stop
  | [d, n, fr, pr, ts, oi, sp, eq, rel, sam, lev, pfrac, stop, gfrac,
     "one", exDirS, exEpS, exSzS] =>
    match Direction.fromString? exDirS with
    | none => IO.eprintln s!"unknown existing direction: {exDirS}"; return 1
    | some exDir =>
      let pos : Position :=
        ⟨exDir, strToRat! exEpS, strToRat! exSzS, 1, 5, 0, "", "", 0⟩
      let port : Gates.Portfolio := ⟨[pos], strToRat! gfrac, []⟩
      parse port d n fr pr ts oi sp eq rel sam lev pfrac stop
  | [d, n, fr, pr, ts, oi, eq, rel, sam, lev, pfrac, stop, gfrac, "none"] =>
    parse ⟨[], strToRat! gfrac, []⟩ d n fr pr ts oi "0" eq rel sam lev pfrac stop
  | [d, n, fr, pr, ts, oi, eq, rel, sam, lev, pfrac, stop, gfrac,
     "one", exDirS, exEpS, exSzS] =>
    match Direction.fromString? exDirS with
    | none => IO.eprintln s!"unknown existing direction: {exDirS}"; return 1
    | some exDir =>
      let pos : Position :=
        ⟨exDir, strToRat! exEpS, strToRat! exSzS, 1, 5, 0, "", "", 0⟩
      let port : Gates.Portfolio := ⟨[pos], strToRat! gfrac, []⟩
      parse port d n fr pr ts oi "0" eq rel sam lev pfrac stop
  | _ =>
    IO.eprintln "usage: veritas-core emit-certificate <dir> <notional> <fr> <price> <ts> <oi> <spot> <equity> <reliability> <sample> <max_lev> <max_pos_frac> <stop_pct> <max_gross_frac> (none | one <exist_dir> <exist_ep> <exist_sz>)"
    return 1

-- ── Entry point ───────────────────────────────────────────────────

private def commandList : String :=
  "gate commands:    verify-signal, check-constraints, check-portfolio, classify-exit, emit-certificate\n" ++
  "primitive commands: decide, extract, size, monitor, update-reliability,\n" ++
  "                   aggregate-reliability, classify-regime, build-context,\n" ++
  "                   judge-signal, execution-quality, version"

def main (args : List String) : IO UInt32 := do
  match args with
  | cmd :: rest =>
    match cmd with
    | "verify-signal"       => handleVerifySignal rest
    | "check-constraints"   => handleCheckConstraints rest
    | "check-portfolio"     => handleCheckPortfolio rest
    | "check-portfolio-ex"  => handleCheckPortfolioEx rest
    | "classify-exit"       => handleClassifyExit rest
    | "emit-certificate"    => handleEmitCertificate rest
    | "emit-certificate-ex" => handleEmitCertificateEx rest
    | "decide"              => handleDecide rest
    | "extract"             => handleExtract rest
    | "decide-basis"        => handleDecideBasis rest
    | "extract-basis"       => handleExtractBasis rest
    | "size"                => handleSize rest
    | "monitor"             => handleMonitor rest
    | "update-reliability"  => handleUpdateReliability rest
    | "aggregate-reliability" => handleAggregateReliability rest
    | "classify-regime"     => handleClassifyRegime rest
    | "build-context"       => handleBuildContext rest
    | "judge-signal"        => handleJudgeSignal rest
    | "execution-quality"   => handleExecutionQuality rest
    | "version"             => IO.println "veritas-core 0.2.0"; return 0
    | _ =>
      IO.eprintln s!"unknown command: {cmd}"
      IO.eprintln commandList
      return 1
  | [] =>
    IO.println "veritas-core 0.2.0 — Lean-backed pre-trade verifier"
    IO.println commandList
    return 0
