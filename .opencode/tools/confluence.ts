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

    if (!baseUrl?.trim() || !email?.trim() || !token?.trim()) {
      throw new Error("NON_RETRYABLE: не заданы переменные окружения Confluence")
    }

    const pageId = args.pageId.trim()

    if (!/^[1-9]\d*$/.test(pageId)) {
      throw new Error("NON_RETRYABLE: pageId должен быть положительным целым числом")
    }

    let base
    try {
      base = new URL(baseUrl.trim())
    } catch {
      throw new Error("NON_RETRYABLE: некорректный CONFLUENCE_URL")
    }
    if (base.protocol !== "https:" || base.username || base.password || base.search || base.hash ||
        !["/", "/wiki", "/wiki/"].includes(base.pathname)) {
      throw new Error("NON_RETRYABLE: CONFLUENCE_URL должен быть HTTPS-адресом сайта или /wiki без credentials, query и fragment")
    }

    const auth = Buffer.from(`${email}:${token}`).toString("base64")
    const url = `${base.origin}/wiki/api/v2/pages/${pageId}?body-format=storage`


    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 15000)
    try {
      let response
      try {
        response = await fetch(url, {
          method: "GET",
          redirect: "error",
          signal: controller.signal,
          headers: {
            Authorization: `Basic ${auth}`,
            Accept: "application/json"
          }
        })
      } catch {
        throw new Error(controller.signal.aborted
          ? "RETRYABLE: таймаут чтения Confluence (15 секунд)"
          : "RETRYABLE: ошибка соединения с Confluence")
      }

      if (!response.ok) {
        if (response.body) await response.body.cancel().catch(() => {})
        const kind = [408, 429, 500, 502, 503, 504].includes(response.status)
          ? "RETRYABLE" : "NON_RETRYABLE"

        throw new Error(`${kind}: Confluence HTTP ${response.status}`)
      }

      let data
      try {
        data = await response.json()
      } catch (error) {
        if (controller.signal.aborted) {
          throw new Error("RETRYABLE: таймаут чтения Confluence (15 секунд)")
        }
        throw new Error(error instanceof SyntaxError
          ? "NON_RETRYABLE: Confluence вернул некорректный JSON"
          : "RETRYABLE: ошибка чтения тела ответа Confluence")
      }

      if (data?.id !== pageId || data?.status !== "current" ||
          typeof data?.title !== "string" || !data.title.trim() ||
          !Number.isSafeInteger(data?.version?.number) || data.version.number < 1 ||
          typeof data?.body?.storage?.value !== "string" || !data.body.storage.value.trim()) {
        throw new Error("NON_RETRYABLE: Confluence вернул неверный ID, статус, версию или пустое содержимое страницы")
      }

      return JSON.stringify(data)
    } finally {
      clearTimeout(timer)
    }
  }
})
