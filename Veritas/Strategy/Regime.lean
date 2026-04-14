/-
  Veritas.Strategy.Regime — Market regime classification.

  First-pass hand-coded classifier (v0.1):
    price_change_24h > +2%  → Bull
    price_change_24h < -2%  → Bear
    otherwise               → Choppy

  This is deliberately crude. The architecture stores raw context
  alongside the tag so future classifiers can retroactively re-tag.
-/
import Veritas.Types

namespace Veritas.Strategy

open Veritas

/-- Classify market regime from 24h price change (decimal, e.g. 0.03 = +3%). -/
def classifyRegime (priceChange24h : Float) : Regime :=
  if priceChange24h > 0.02 then .Bull
  else if priceChange24h < -0.02 then .Bear
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
def priceChange24h (currentPrice prevDayPrice : Float) : Float :=
  if prevDayPrice > 0.0 then (currentPrice - prevDayPrice) / prevDayPrice
  else 0.0

end Veritas.Strategy
