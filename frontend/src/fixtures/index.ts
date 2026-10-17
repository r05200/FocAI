// Typed access to the generated fixtures. Regenerate the JSON with:
//   cd backend && uv run python -m pruner.fixtures
// The `as unknown as` casts are needed because JSON imports widen string literals;
// the real shape check happens in backend/tests.
import type { PrunerEvent, RunSnapshot, VaultGraph, VaultItemView } from '../types'
import runEvents from './run_events.json'
import runSnapshot from './run_snapshot.json'
import vaultGraph from './vault_graph.json'
import vaultItems from './vault_items.json'

// FLAG (ignore unless asked): the `as unknown as` casts hide shape drift, so tsc will not catch a mismatch with the backend.
export const fixtureEvents = runEvents as unknown as PrunerEvent[]
export const fixtureSnapshot = runSnapshot as unknown as RunSnapshot
export const fixtureVaultGraph = vaultGraph as unknown as VaultGraph
export const fixtureVaultItems = vaultItems as unknown as VaultItemView[]
