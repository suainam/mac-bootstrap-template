import { test, expect } from "bun:test"
import { OperationBoundaries, boundaryFor } from "../agent/omp/extensions/operation-boundaries"

test("normal auth passes, sensitive calls require one operator grant", () => {
  const g = new OperationBoundaries(); g.switchSession("one")
  const call = (command: string) => ({ toolName: "bash", input: { command } })
  expect(g.check(call("gh auth status"))).toBeUndefined()
  expect(g.check(call("gh issue create --body-file draft"))).toBeUndefined()
  expect(g.check(call("security dump-keychain"))?.block).toBe(true)
  g.allow("credentials")
  expect(g.check(call("security dump-keychain"))).toBeUndefined()
  expect(g.check(call("security find-generic-password -s gh -w"))?.block).toBe(true)
  g.allow("credentials"); g.switchSession("two")
  expect(g.check(call("security dump-keychain"))?.block).toBe(true)
})

test("isolated browser allowed, explicit profile and adoption guarded", () => {
  const check = (command: string) => boundaryFor({ toolName: "bash", input: { command } })
  expect(check("agent-browser --session diagnostic open https://example.com")).toBeUndefined()
  expect(check("agent-browser --profile='Default' open https://example.com")).toBe("browser")
  expect(check('agent-browser --profile "Default" open https://example.com')).toBe("browser")
  expect(boundaryFor({ toolName: "eval", input: { code: 'browser.open({app:{relay:true}})' } })).toBe("browser")
})
