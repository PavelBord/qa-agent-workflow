import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "Получить страницу Confluence по pageId",

  args: {
    pageId: tool.schema.string()
  },

  async execute(args) {
    const baseUrl = process.env.CONFLUENCE_URL
    const email = process.env.CONFLUENCE_EMAIL
    const token = process.env.CONFLUENCE_API_TOKEN

    if (!baseUrl || !email || !token) {
      throw new Error("Не заданы переменные окружения Confluence")
    }

    const pageId = args.pageId.trim()

    if (!pageId) {
      throw new Error("Не указан pageId")
    }

    const auth = Buffer.from(`${email}:${token}`).toString("base64")

    const url =
      `${baseUrl.replace(/\/$/, "")}` +
      `/wiki/api/v2/pages/${encodeURIComponent(pageId)}` +
      `?body-format=storage`

    const response = await fetch(url, {
      method: "GET",
      headers: {
        Authorization: `Basic ${auth}`,
        Accept: "application/json"
      }
    })

    if (!response.ok) {
      throw new Error(
        `Confluence API error for pageId=${pageId}: ` +
        `${response.status} ${response.statusText}`
      )
    }

    const data = await response.json()

    if (!data?.id || !data?.body) {
      throw new Error(
        `Confluence returned invalid page data for pageId=${pageId}`
      )
    }

    return JSON.stringify(data)
  }
})