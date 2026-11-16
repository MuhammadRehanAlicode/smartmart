module.exports = {
  content: ["./templates/**/*.html", "./apps/**/*.py", "./static/js/**/*.js"],
  theme: {
    extend: {
      colors: {
        primary: "#126B50", canvas: "#F8F5EC", accent: "#F2A541",
        ink: "#202824", muted: "#6B756F", line: "#E4E9E4",
      },
      boxShadow: { card: "0 1px 3px rgba(32,40,36,.08), 0 1px 2px rgba(32,40,36,.04)" },
    },
  },
};
