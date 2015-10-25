xgettext -d cf-gui -s -j -o locale/cf-gui.pot cf-gui.py
for i in locale/??_??; do
	msgmerge -vU $i/LC_MESSAGES/cf-gui.po locale/cf-gui.pot;
	msgcat $i/LC_MESSAGES/*.po | msgfmt -vo $i/LC_MESSAGES/cf-gui.mo -
done
