/-
  Veritas.Strategy.Regime — Market regime classification.

  v0.2 Slice 5: thresholds migrated to exact `Rat`.
-/
import Veritas.Types
import Mathlib.Data.Rat.Defs

namespace Veritas.Strategy

open Veritas

/-- Classify market regime from 24h price change (decimal, e.g. 3/100 = +3%). -/
def classifyRegime (priceChange24h : Rat) : Regime :=
  if priceChange24h > 1 / 50 then .Bull
  else if priceChange24h < -(1 / 50) then .Bear
  else .Choppy

end Veritas.Strategy

namespace Veritas.Regime

def toString : Veritas.Regime → String
  | .Bull    => "bull"
  | .Bear    => "bear"
  | .Choppy  => "choppy"
  | .Unknown => "unknown"

end Veritas.Regime

namespace Veritas.Strategy

/-- Build the price_change_24h from current and previous day price. -/
def priceChange24h (currentPrice prevDayPrice : Rat) : Rat :=
  if prevDayPrice > 0 then (currentPrice - prevDayPrice) / prevDayPrice
  else 0

end Veritas.Strategy
