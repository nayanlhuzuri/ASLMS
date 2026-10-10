/** One line per web-server request: method, path, status and duration only; never bodies, cookies or tokens. */
export function withLog(handler: (request: Request) => Promise<Response>) {
  return async (request: Request): Promise<Response> => {
    const started = Date.now();
    let status = 500;
    try {
      const response = await handler(request);
      status = response.status;
      return response;
    } finally {
      const path = new URL(request.url).pathname;
      console.info(JSON.stringify({ method: request.method, path, status, ms: Date.now() - started }));
    }
  };
}
