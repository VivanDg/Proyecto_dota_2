/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    // onnxruntime-node trae binarios nativos; hay que excluirlo del bundling
    // para que Next.js lo resuelva vía require() normal en runtime Node.
    serverComponentsExternalPackages: ["onnxruntime-node"],
  },
};

module.exports = nextConfig;
