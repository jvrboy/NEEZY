import "./globals.css";

export const metadata = {
  title: "NEEZY Executor",
  description: "Read-only monitoring for the NEEZY lightweight demo executor",
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#07110f",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
