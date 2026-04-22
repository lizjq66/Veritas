import Lake
open Lake DSL

require "leanprover-community" / "mathlib" @ git "v4.29.0"

package «veritas» where
  leanOptions := #[⟨`autoImplicit, false⟩]

lean_lib «Veritas» where
  srcDir := "."

@[default_target]
lean_exe «veritas-core» where
  root := `Veritas.Main
