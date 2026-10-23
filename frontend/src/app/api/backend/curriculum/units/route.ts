import { failure } from "@/lib/server/auth";
import { get, queryString } from "@/lib/server/bff";
export async function GET(request: Request) {
  try {
    return await get(request, "/v1/curriculum/units" + queryString(request, ["subject","grade","programYear"]));
  } catch (error) { return failure(error); }
}
