/-
  Veritas.Main — CLI entry point for the Lean verified core.

  Invoked by Python bridge as:
    veritas-core <command> <args...>

  Commands:
    decide <funding_rate> <btc_price> <timestamp> [open_interest]
    extract <direction> <funding_rate> <price>
    size <equity> <reliability>
    monitor <funding_rate> <btc_price> <timestamp> <open_interest>
            <direction> <entry_price> <size> <leverage> <stop_loss_pct>
            <entry_timestamp> <assumption_name>
    update-reliability <wins> <total> <exit_reason>

  Output: JSON to stdout.
-/
import Lean.Data.Json.Parser
import Veritas.Types
import Veritas.Finance.PositionSizing
import Veritas.Strategy.FundingReversion
import Veritas.Strategy.ExitLogic
import Veritas.Strategy.Regime
import Veritas.Learning.Reliability
import Veritas.Finance.ExecutionQuality

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

-- ── Command handlers ──────────────────────────────────────────────

private def handleDecide (args : List String) : IO UInt32 := do
  let (frS, priceS, tsS, oiS) ← match args with
    | [a, b, c]    => pure (a, b, c, "0")
    | [a, b, c, d] => pure (a, b, c, d)
    | _ => IO.eprintln "usage: veritas-core decide <fr> <price> <ts> [oi]"; return 1
  let snapshot : MarketSnapshot :=
    ⟨strToFloat! frS, strToFloat! priceS, tsS.toNat!, strToFloat! oiS⟩
  match Strategy.decide snapshot with
  | some signal =>
    IO.println (jsonObj [jsonStr "action" "signal",
                         jsonStr "direction" signal.direction.toString,
                         jsonNum "funding_rate" signal.fundingRate,
                         jsonNum "price" signal.price])
  | none =>
    IO.println "null"
  return 0

private def handleExtract (args : List String) : IO UInt32 := do
  match args with
  | [dirS, frS, priceS] =>
    match Direction.fromString? dirS with
    | none => IO.eprintln s!"unknown direction: {dirS}"; return 1
    | some dir =>
      let signal : Signal := ⟨dir, strToFloat! frS, strToFloat! priceS⟩
      let assumptions := Strategy.extractAssumptions signal
      let jsons := assumptions.map fun a =>
        jsonObj [jsonStr "name" a.name, jsonStr "description" a.description]
      IO.println s!"[{", ".intercalate jsons}]"
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
        ⟨strToFloat! frS, strToFloat! priceS, tsS.toNat!, strToFloat! oiS⟩
      let position : Position :=
        ⟨dir, strToFloat! epS, strToFloat! szS, strToFloat! levS,
         strToFloat! slS, etsS.toNat!, aname⟩
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

-- ── Entry point ───────────────────────────────────────────────────

def main (args : List String) : IO UInt32 := do
  match args with
  | cmd :: rest =>
    match cmd with
    | "decide"             => handleDecide rest
    | "extract"            => handleExtract rest
    | "size"               => handleSize rest
    | "monitor"            => handleMonitor rest
    | "update-reliability"  => handleUpdateReliability rest
    | "classify-regime"     => handleClassifyRegime rest
    | "build-context"       => handleBuildContext rest
    | "judge-signal"        => handleJudgeSignal rest
    | "execution-quality"   => handleExecutionQuality rest
    | "version"             => IO.println "veritas-core 0.1.0"; return 0
    | _ =>
      IO.eprintln s!"unknown command: {cmd}"
      IO.eprintln "commands: decide, extract, size, monitor, update-reliability, version"
      return 1
  | [] =>
    IO.println "veritas-core 0.1.0 — Lean-native verified trading core"
    IO.println "commands: decide, extract, size, monitor, update-reliability, version"
    return 0
