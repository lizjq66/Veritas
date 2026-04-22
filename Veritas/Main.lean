/-
  Veritas.Main — CLI entry point for the Lean verification kernel.

  Veritas is a pre-trade verifier. A calling trading agent submits a
  proposed trade via one of the gate commands, and Veritas returns a
  structured approve / resize / reject verdict with reason codes.

  Gate commands (the product surface):
    verify-signal      <dir> <fr> <price> <ts> <oi> <notional>
    check-constraints  <dir> <notional> <equity> <reliability>
                       <sample_size> <max_leverage> <max_pos_frac> <stop_pct>
    check-portfolio    <dir> <notional> <equity> <max_gross_frac>
                       <existing_positions_json>
    classify-exit      (see `monitor` below — same implementation)
    emit-certificate   <proposal_json> <constraints_json> <portfolio_json>

  Primitive commands (building blocks; callable by adapters and demos):
    decide             <fr> <price> <ts> [oi]
    extract            <dir> <fr> <price>
    size               <equity> <reliability> <sample_size>
    monitor            <fr> <price> <ts> <oi> <dir> <ep> <sz> <lev> <sl>
                       <ets> <aname>
    update-reliability <wins> <total> <exit_reason>
    classify-regime    <price_change_24h>
    build-context      <fr> <price> <oi> <vol> <prem> <spread> <prev_price>
    judge-signal       <exit_reason>
    execution-quality  <mark> <fill> <exit> <expected> <realized>

  Output: JSON to stdout. Errors to stderr with nonzero exit code.
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

-- ── String → Float parser (Lean 4 stdlib lacks String.toFloat!) ──

/-- Parse a numeric string to Float via Lean's JSON number parser.
    JsonNumber stores mantissa : Int, exponent : Nat where
    value = mantissa × 10^(−exponent). -/
private def strToFloat! (s : String) : Float :=
  match Lean.Json.parse s with
  | .ok (.num n) =>
    let absM := n.mantissa.natAbs
    let neg := n.mantissa < 0
    let f := Float.ofScientific absM true n.exponent
    if neg then -f else f
  | _ => panic! s!"strToFloat!: cannot parse '{s}'"

-- ── JSON output helpers ───────────────────────────────────────────

private def jsonStr (k v : String) : String := s!"\"{k}\": \"{v}\""
private def jsonNum (k : String) (v : Float) : String := s!"\"{k}\": {v}"
private def jsonNat (k : String) (v : Nat) : String := s!"\"{k}\": {v}"
private def jsonObj (fields : List String) : String :=
  "{ " ++ ", ".intercalate fields ++ " }"

/-- Serialize a list of string reason codes as a JSON array. -/
private def jsonCodes (codes : List String) : String :=
  let quoted := codes.map (fun c => s!"\"{c}\"")
  "[" ++ ", ".intercalate quoted ++ "]"

/-- Serialize a list of assumptions as a JSON array of {name, description}. -/
private def jsonAssumptions (xs : List Assumption) : String :=
  let items := xs.map fun a =>
    jsonObj [jsonStr "name" a.name, jsonStr "description" a.description]
  "[" ++ ", ".intercalate items ++ "]"

/-- Serialize a verdict as a compact JSON object. -/
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
    ⟨strToFloat! frS, strToFloat! priceS, tsS.toNat!, strToFloat! oiS, 0.0⟩
  match Strategy.decide snapshot with
  | some signal =>
    IO.println (jsonObj [jsonStr "action" "signal",
                         jsonStr "direction" signal.direction.toString,
                         jsonNum "funding_rate" signal.fundingRate,
                         jsonNum "price" signal.price])
  | none =>
    IO.println "null"
  return 0

/-- Basis-reversion strategy decider (v0.2 Slice 1).
    Takes spot price explicitly; funding rate and open interest are
    passed through for completeness but not consulted by the basis
    strategy itself. -/
private def handleDecideBasis (args : List String) : IO UInt32 := do
  match args with
  | [perpS, spotS, tsS] =>
    let snapshot : MarketSnapshot :=
      ⟨0.0, strToFloat! perpS, tsS.toNat!, 0.0, strToFloat! spotS⟩
    match Strategy.decideBasis snapshot with
    | some signal =>
      IO.println (jsonObj [jsonStr "action" "signal",
                           jsonStr "strategy" "basis_reversion",
                           jsonStr "direction" signal.direction.toString,
                           jsonNum "perp_price" signal.price,
                           jsonNum "spot_price" (strToFloat! spotS)])
      return 0
    | none =>
      IO.println "null"; return 0
  | _ =>
    IO.eprintln "usage: veritas-core decide-basis <perp_price> <spot_price> <timestamp>"
    return 1

/-- Extract basis-reversion assumptions for a signal. -/
private def handleExtractBasis (args : List String) : IO UInt32 := do
  match args with
  | [dirS, perpS] =>
    match Direction.fromString? dirS with
    | none => IO.eprintln s!"unknown direction: {dirS}"; return 1
    | some dir =>
      let signal : Signal := ⟨dir, 0.0, strToFloat! perpS⟩
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
      let signal : Signal := ⟨dir, strToFloat! frS, strToFloat! priceS⟩
      let assumptions := Strategy.extractAssumptions signal
      IO.println (jsonAssumptions assumptions)
      return 0
  | _ =>
    IO.eprintln "usage: veritas-core extract <direction> <fr> <price>"
    return 1

private def handleSize (args : List String) : IO UInt32 := do
  match args with
  | [equityS, relS, sampleS] =>
    let size := Finance.calculatePositionSize (strToFloat! equityS) (strToFloat! relS) sampleS.toNat!
    IO.println (jsonObj [jsonNum "position_size" size,
                         jsonNum "equity" (strToFloat! equityS),
                         jsonNum "reliability" (strToFloat! relS)])
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
        ⟨strToFloat! frS, strToFloat! priceS, tsS.toNat!, strToFloat! oiS, 0.0⟩
      let position : Position :=
        ⟨dir, strToFloat! epS, strToFloat! szS, strToFloat! levS,
         strToFloat! slS, etsS.toNat!, aname, ""⟩
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
    let pc := strToFloat! priceChangeS
    let regime := Strategy.classifyRegime pc
    IO.println (jsonObj [jsonStr "regime" regime.toString])
    return 0
  | _ =>
    IO.eprintln "usage: veritas-core classify-regime <price_change_24h>"
    return 1

private def handleBuildContext (args : List String) : IO UInt32 := do
  match args with
  | [frS, priceS, oiS, volS, premS, spreadS, prevS] =>
    let price := strToFloat! priceS
    let prev := strToFloat! prevS
    let pc := Strategy.priceChange24h price prev
    let regime := Strategy.classifyRegime pc
    IO.println (jsonObj [
      jsonNum "funding_rate" (strToFloat! frS),
      jsonNum "asset_price" price,
      jsonNum "open_interest" (strToFloat! oiS),
      jsonNum "volume_24h" (strToFloat! volS),
      jsonNum "premium" (strToFloat! premS),
      jsonNum "price_change_24h" pc,
      jsonNum "spread_bps" (strToFloat! spreadS),
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
    let mark := strToFloat! markS
    let fill := strToFloat! fillS
    let exit := strToFloat! exitS
    let expected := strToFloat! expectedS
    let realized := strToFloat! realizedS
    IO.println (jsonObj [
      jsonNum "slippage_bps" (Finance.slippageBps mark fill),
      jsonNum "price_impact_bps" (Finance.priceImpactBps mark exit),
      jsonNum "realized_vs_expected_pnl" (Finance.realizedVsExpectedPnl realized expected)])
    return 0
  | _ =>
    IO.eprintln "usage: veritas-core execution-quality <mark> <fill> <exit> <expected_pnl> <realized_pnl>"
    return 1

-- ── Gate command handlers ────────────────────────────────────────

/-- Positional-argument form. A richer JSON entry point lives in
    `emit-certificate`. -/
private def handleVerifySignal (args : List String) : IO UInt32 := do
  let parse := fun (dirS notionalS frS priceS tsS oiS spotS : String) => do
    match Direction.fromString? dirS with
    | none => IO.eprintln s!"unknown direction: {dirS}"; return (1 : UInt32)
    | some dir =>
      let proposal : Gates.TradeProposal :=
        ⟨dir, strToFloat! notionalS, strToFloat! frS, strToFloat! priceS,
         tsS.toNat!, strToFloat! oiS, strToFloat! spotS, ""⟩
      let (verdict, assumptions) := Gates.verifySignal proposal
      IO.println (jsonObj [
        jsonStr "gate" "1",
        jsonStr "name" "signal_consistency",
        s!"\"result\": {jsonVerdict verdict}",
        s!"\"assumptions\": {jsonAssumptions assumptions}"])
      return 0
  match args with
  -- v0.2+ form: spot_price explicit (7 args)
  | [dirS, frS, priceS, tsS, oiS, notionalS, spotS] =>
    parse dirS notionalS frS priceS tsS oiS spotS
  -- v0.1 back-compat: no spot_price (6 args); default to 0.0
  | [dirS, frS, priceS, tsS, oiS, notionalS] =>
    parse dirS notionalS frS priceS tsS oiS "0.0"
  | _ =>
    IO.eprintln "usage: veritas-core verify-signal <dir> <fr> <price> <ts> <oi> <notional> [spot_price]"
    return 1

private def handleCheckConstraints (args : List String) : IO UInt32 := do
  match args with
  | [dirS, notionalS, equityS, relS, sampleS, maxLevS, maxFracS, stopPctS] =>
    match Direction.fromString? dirS with
    | none => IO.eprintln s!"unknown direction: {dirS}"; return 1
    | some dir =>
      -- Placeholders for fields not used by Gate 2 itself.
      let proposal : Gates.TradeProposal :=
        ⟨dir, strToFloat! notionalS, 0.0, 0.0, 0, 0.0, 0.0, ""⟩
      let constraints : Gates.AccountConstraints :=
        ⟨strToFloat! equityS, strToFloat! maxFracS, strToFloat! maxLevS,
         strToFloat! stopPctS, strToFloat! relS, sampleS.toNat!⟩
      let verdict := Gates.checkConstraints proposal constraints
      IO.println (jsonObj [
        jsonStr "gate" "2",
        jsonStr "name" "strategy_constraint_compatibility",
        s!"\"result\": {jsonVerdict verdict}"])
      return 0
  | _ =>
    IO.eprintln "usage: veritas-core check-constraints <dir> <notional> <equity> <reliability> <sample_size> <max_leverage> <max_pos_frac> <stop_pct>"
    return 1

/-- Parse a flat list of strings as correlation triples
    `(assetA, assetB, coefficient)`. Returns `some []` for empty input
    and `none` if the list length is not a multiple of 3. -/
private partial def parseCorrelationTriples
    : List String → Option (List Gates.CorrelationEntry)
  | []                      => some []
  | a :: b :: c :: rest     =>
    match parseCorrelationTriples rest with
    | some tail => some (⟨a, b, strToFloat! c⟩ :: tail)
    | none      => none
  | _                       => none

/-- v0.1 Gate 3 positional form: caller passes its own position
    summary as seven flat fields, or "none" to indicate no position.

    Call shape (no position):
      check-portfolio <dir> <notional> <equity> <max_gross_frac> none

    Call shape (one existing position on the same asset):
      check-portfolio <dir> <notional> <equity> <max_gross_frac>
                      one <existing_dir> <existing_entry_price> <existing_size>
-/
private def handleCheckPortfolio (args : List String) : IO UInt32 := do
  match args with
  | [dirS, notionalS, equityS, maxFracS, "none"] =>
    match Direction.fromString? dirS with
    | none => IO.eprintln s!"unknown direction: {dirS}"; return 1
    | some dir =>
      let proposal : Gates.TradeProposal :=
        ⟨dir, strToFloat! notionalS, 0.0, 0.0, 0, 0.0, 0.0, ""⟩
      let port : Gates.Portfolio := ⟨[], strToFloat! maxFracS, []⟩
      let verdict := Gates.checkPortfolio proposal port (strToFloat! equityS)
      IO.println (jsonObj [
        jsonStr "gate" "3",
        jsonStr "name" "portfolio_interference",
        s!"\"result\": {jsonVerdict verdict}"])
      return 0
  | [dirS, notionalS, equityS, maxFracS, "one", exDirS, exEpS, exSzS] =>
    match Direction.fromString? dirS, Direction.fromString? exDirS with
    | some dir, some exDir =>
      let proposal : Gates.TradeProposal :=
        ⟨dir, strToFloat! notionalS, 0.0, 0.0, 0, 0.0, 0.0, ""⟩
      let pos : Position :=
        ⟨exDir, strToFloat! exEpS, strToFloat! exSzS, 1.0, 5.0, 0, "", ""⟩
      let port : Gates.Portfolio := ⟨[pos], strToFloat! maxFracS, []⟩
      let verdict := Gates.checkPortfolio proposal port (strToFloat! equityS)
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

/-- Alias for `monitor` under gate-vocabulary naming. -/
private def handleClassifyExit (args : List String) : IO UInt32 :=
  handleMonitor args

/-- v0.2 Gate 3 extended positional form with asset tagging and
    correlation entries.

    Shape (no existing position):
      check-portfolio-ex <dir> <notional> <equity> <max_gross_frac>
                         <prop_asset> none
                         <n_corr> [<a> <b> <c>]*

    Shape (one existing position):
      check-portfolio-ex <dir> <notional> <equity> <max_gross_frac>
                         <prop_asset>
                         one <exist_dir> <exist_ep> <exist_sz> <exist_asset>
                         <n_corr> [<a> <b> <c>]*
-/
private def handleCheckPortfolioEx (args : List String) : IO UInt32 := do
  let usage :=
    "usage: veritas-core check-portfolio-ex <dir> <notional> <equity> " ++
    "<max_gross_frac> <prop_asset> (none | one <ed> <ep> <sz> <asset>) " ++
    "<n_corr> [<a> <b> <c>]*"
  match args with
  | dirS :: notionalS :: equityS :: maxFracS :: propAssetS
      :: "none" :: _nCorrS :: corrArgs =>
    match Direction.fromString? dirS,
          parseCorrelationTriples corrArgs with
    | some dir, some corrs =>
      let proposal : Gates.TradeProposal :=
        ⟨dir, strToFloat! notionalS, 0.0, 0.0, 0, 0.0, 0.0, propAssetS⟩
      let port : Gates.Portfolio := ⟨[], strToFloat! maxFracS, corrs⟩
      let verdict := Gates.checkPortfolio proposal port (strToFloat! equityS)
      IO.println (jsonObj [
        jsonStr "gate" "3",
        jsonStr "name" "portfolio_interference",
        s!"\"result\": {jsonVerdict verdict}"])
      return 0
    | _, _ => IO.eprintln usage; return 1
  | dirS :: notionalS :: equityS :: maxFracS :: propAssetS
      :: "one" :: exDirS :: exEpS :: exSzS :: exAssetS
      :: _nCorrS :: corrArgs =>
    match Direction.fromString? dirS,
          Direction.fromString? exDirS,
          parseCorrelationTriples corrArgs with
    | some dir, some exDir, some corrs =>
      let proposal : Gates.TradeProposal :=
        ⟨dir, strToFloat! notionalS, 0.0, 0.0, 0, 0.0, 0.0, propAssetS⟩
      let pos : Position :=
        ⟨exDir, strToFloat! exEpS, strToFloat! exSzS, 1.0, 5.0, 0, "", exAssetS⟩
      let port : Gates.Portfolio := ⟨[pos], strToFloat! maxFracS, corrs⟩
      let verdict := Gates.checkPortfolio proposal port (strToFloat! equityS)
      IO.println (jsonObj [
        jsonStr "gate" "3",
        jsonStr "name" "portfolio_interference",
        s!"\"result\": {jsonVerdict verdict}"])
      return 0
    | _, _, _ => IO.eprintln usage; return 1
  | _ => IO.eprintln usage; return 1

/-- v0.2 combined certificate with asset tagging and correlation
    entries. Shape mirrors check-portfolio-ex: the whole arg list is
    positional, with a trailing correlation block.

    Args:
      <dir> <notional> <fr> <price> <ts> <oi> <spot>
      <equity> <rel> <sample> <max_lev> <max_pos_frac> <stop_pct>
      <max_gross_frac> <prop_asset>
      (none | one <ed> <ep> <sz> <asset>)
      <n_corr> [<a> <b> <c>]*
-/
private def handleEmitCertificateEx (args : List String) : IO UInt32 := do
  let usage :=
    "usage: veritas-core emit-certificate-ex <dir> <notional> <fr> " ++
    "<price> <ts> <oi> <spot> <equity> <rel> <sample> <max_lev> " ++
    "<max_pos_frac> <stop_pct> <max_gross_frac> <prop_asset> " ++
    "(none | one <ed> <ep> <sz> <asset>) <n_corr> [<a> <b> <c>]*"
  let buildAndEmit := fun (port : Gates.Portfolio)
                          (dirStr : String) (notionalStr frStr priceStr : String)
                          (tsStr oiStr spotStr : String)
                          (equityStr relStr sampleStr : String)
                          (maxLevStr maxFracStr stopPctStr : String)
                          (propAsset : String) => do
    match Direction.fromString? dirStr with
    | none => IO.eprintln s!"unknown direction: {dirStr}"; return (1 : UInt32)
    | some dir =>
      let proposal : Gates.TradeProposal :=
        ⟨dir, strToFloat! notionalStr, strToFloat! frStr, strToFloat! priceStr,
         tsStr.toNat!, strToFloat! oiStr, strToFloat! spotStr, propAsset⟩
      let constraints : Gates.AccountConstraints :=
        ⟨strToFloat! equityStr, strToFloat! maxFracStr, strToFloat! maxLevStr,
         strToFloat! stopPctStr, strToFloat! relStr, sampleStr.toNat!⟩
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
      :: eq :: rel :: sam :: lev :: pfrac :: stop
      :: gfrac :: propAsset :: "none" :: _nCorrS :: corrArgs =>
    match parseCorrelationTriples corrArgs with
    | some corrs =>
      let port : Gates.Portfolio := ⟨[], strToFloat! gfrac, corrs⟩
      buildAndEmit port d n fr pr ts oi sp eq rel sam lev pfrac stop propAsset
    | none => IO.eprintln usage; return 1
  | d :: n :: fr :: pr :: ts :: oi :: sp
      :: eq :: rel :: sam :: lev :: pfrac :: stop
      :: gfrac :: propAsset
      :: "one" :: exDirS :: exEpS :: exSzS :: exAssetS
      :: _nCorrS :: corrArgs =>
    match Direction.fromString? exDirS, parseCorrelationTriples corrArgs with
    | some exDir, some corrs =>
      let pos : Position :=
        ⟨exDir, strToFloat! exEpS, strToFloat! exSzS, 1.0, 5.0, 0, "", exAssetS⟩
      let port : Gates.Portfolio := ⟨[pos], strToFloat! gfrac, corrs⟩
      buildAndEmit port d n fr pr ts oi sp eq rel sam lev pfrac stop propAsset
    | _, _ => IO.eprintln usage; return 1
  | _ => IO.eprintln usage; return 1

/-- Full certificate: run all three gates in sequence and emit the trace.

    This is the richest positional form; adapters that want structured
    input can still call the individual gates one at a time.

    Args: <dir> <notional> <fr> <price> <ts> <oi>
          <equity> <reliability> <sample_size> <max_leverage>
          <max_pos_frac> <stop_pct> <max_gross_frac>
          (none | one <exist_dir> <exist_ep> <exist_sz>) -/
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
        ⟨dir, strToFloat! notionalStr, strToFloat! frStr, strToFloat! priceStr,
         tsStr.toNat!, strToFloat! oiStr, strToFloat! spotStr, ""⟩
      let constraints : Gates.AccountConstraints :=
        ⟨strToFloat! equityStr, strToFloat! maxFracStr, strToFloat! maxLevStr,
         strToFloat! stopPctStr, strToFloat! relStr, sampleStr.toNat!⟩
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
  -- v0.2+ form: spot_price after oi (15 args + "none" / 18 args + "one" ...)
  | [d, n, fr, pr, ts, oi, sp, eq, rel, sam, lev, pfrac, stop, gfrac, "none"] =>
    parse ⟨[], strToFloat! gfrac, []⟩ d n fr pr ts oi sp eq rel sam lev pfrac stop
  | [d, n, fr, pr, ts, oi, sp, eq, rel, sam, lev, pfrac, stop, gfrac,
     "one", exDirS, exEpS, exSzS] =>
    match Direction.fromString? exDirS with
    | none => IO.eprintln s!"unknown existing direction: {exDirS}"; return 1
    | some exDir =>
      let pos : Position :=
        ⟨exDir, strToFloat! exEpS, strToFloat! exSzS, 1.0, 5.0, 0, "", ""⟩
      let port : Gates.Portfolio := ⟨[pos], strToFloat! gfrac, []⟩
      parse port d n fr pr ts oi sp eq rel sam lev pfrac stop
  -- v0.1 back-compat: no spot_price
  | [d, n, fr, pr, ts, oi, eq, rel, sam, lev, pfrac, stop, gfrac, "none"] =>
    parse ⟨[], strToFloat! gfrac, []⟩ d n fr pr ts oi "0.0" eq rel sam lev pfrac stop
  | [d, n, fr, pr, ts, oi, eq, rel, sam, lev, pfrac, stop, gfrac,
     "one", exDirS, exEpS, exSzS] =>
    match Direction.fromString? exDirS with
    | none => IO.eprintln s!"unknown existing direction: {exDirS}"; return 1
    | some exDir =>
      let pos : Position :=
        ⟨exDir, strToFloat! exEpS, strToFloat! exSzS, 1.0, 5.0, 0, "", ""⟩
      let port : Gates.Portfolio := ⟨[pos], strToFloat! gfrac, []⟩
      parse port d n fr pr ts oi "0.0" eq rel sam lev pfrac stop
  | _ =>
    IO.eprintln "usage: veritas-core emit-certificate <dir> <notional> <fr> <price> <ts> <oi> <spot> <equity> <reliability> <sample> <max_lev> <max_pos_frac> <stop_pct> <max_gross_frac> (none | one <exist_dir> <exist_ep> <exist_sz>)"
    return 1

-- ── Entry point ───────────────────────────────────────────────────

/-- Commands listed in the help banner. -/
private def commandList : String :=
  "gate commands:    verify-signal, check-constraints, check-portfolio, classify-exit, emit-certificate\n" ++
  "primitive commands: decide, extract, size, monitor, update-reliability,\n" ++
  "                   classify-regime, build-context, judge-signal, execution-quality, version"

def main (args : List String) : IO UInt32 := do
  match args with
  | cmd :: rest =>
    match cmd with
    -- Gate surface (new product vocabulary)
    | "verify-signal"       => handleVerifySignal rest
    | "check-constraints"   => handleCheckConstraints rest
    | "check-portfolio"     => handleCheckPortfolio rest
    | "check-portfolio-ex"  => handleCheckPortfolioEx rest
    | "classify-exit"       => handleClassifyExit rest
    | "emit-certificate"    => handleEmitCertificate rest
    | "emit-certificate-ex" => handleEmitCertificateEx rest
    -- Primitive commands (building blocks)
    | "decide"              => handleDecide rest
    | "extract"             => handleExtract rest
    -- BasisReversion primitives (v0.2 Slice 1; not yet wired into Gate 1)
    | "decide-basis"        => handleDecideBasis rest
    | "extract-basis"       => handleExtractBasis rest
    | "size"                => handleSize rest
    | "monitor"             => handleMonitor rest
    | "update-reliability"  => handleUpdateReliability rest
    | "classify-regime"     => handleClassifyRegime rest
    | "build-context"       => handleBuildContext rest
    | "judge-signal"        => handleJudgeSignal rest
    | "execution-quality"   => handleExecutionQuality rest
    | "version"             => IO.println "veritas-core 0.1.0"; return 0
    | _ =>
      IO.eprintln s!"unknown command: {cmd}"
      IO.eprintln commandList
      return 1
  | [] =>
    IO.println "veritas-core 0.1.0 — Lean-backed pre-trade verifier"
    IO.println commandList
    return 0
