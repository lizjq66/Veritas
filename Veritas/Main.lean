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
import Veritas.Learning.Reliability

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

-- ── Entry point ───────────────────────────────────────────────────

def main (args : List String) : IO UInt32 := do
  match args with
  | cmd :: rest =>
    match cmd with
    | "decide"             => handleDecide rest
    | "extract"            => handleExtract rest
    | "size"               => handleSize rest
    | "monitor"            => handleMonitor rest
    | "update-reliability" => handleUpdateReliability rest
    | "version"            => IO.println "veritas-core 0.1.0"; return 0
    | _ =>
      IO.eprintln s!"unknown command: {cmd}"
      IO.eprintln "commands: decide, extract, size, monitor, update-reliability, version"
      return 1
  | [] =>
    IO.println "veritas-core 0.1.0 — Lean-native verified trading core"
    IO.println "commands: decide, extract, size, monitor, update-reliability, version"
    return 0
