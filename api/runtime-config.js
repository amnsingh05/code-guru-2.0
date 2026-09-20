// Vercel Serverless Function: GET /api/runtime-config
// Set CODEGURU_API_URL in Vercel Project Settings → Environment Variables.
module.exports = function handler(request, response) {
  const apiUrl = process.env.CODEGURU_API_URL || '';
  response.setHeader('Cache-Control', 'no-store');
  response.status(200).json({ apiUrl });
};
