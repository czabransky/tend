class Tend < Formula
  desc "Run dev commands in the background as launchd jobs, with an fzf job manager"
  homepage "https://github.com/czabransky/tend"
  head "https://github.com/czabransky/tend.git", branch: "main"
  license "Unlicense"

  depends_on "fzf"
  depends_on :macos

  def install
    # Homebrew requires the Command Line Tools, which provide /usr/bin/python3.
    inreplace "tend", "#!/usr/bin/env python3", "#!/usr/bin/python3"
    bin.install "tend"
  end

  test do
    assert_match "tend #{version}", shell_output("#{bin}/tend --version") if build.stable?
    assert_match "no jobs", shell_output("HOME=#{testpath} #{bin}/tend ls")
  end
end
