#!/usr/bin/env python3
"""Interactive scanner for LeBonCoin property ads with local caching.

Usage:
  python3 scripts/interactive_scanner.py --city Nantes --query loyer --cache cache.json
  
With AI analysis:
  GROQ_API_KEY=your_key python3 scripts/interactive_scanner.py --city Nantes --query loyer --cache cache.json
"""

import argparse
import json
import os
import sys
import requests
from datetime import datetime
from pathlib import Path
from scan_lbc import parse_ad_page, build_search_url, extract_ad_links_from_search, fetch, HEADERS

try:
    from analyze_property import get_ai_analysis, extract_annonce_text
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False


class PropertyCache:
    """Manage local cache of property data and analyses."""
    
    def __init__(self, cache_file):
        self.cache_file = cache_file
        self.data = {}
        self.load()
    
    def load(self):
        """Load cache from file."""
        if Path(self.cache_file).exists():
            try:
                with open(self.cache_file, 'r') as f:
                    self.data = json.load(f)
                print(f"📂 Cache chargé: {len(self.data)} annonces")
            except Exception as e:
                print(f"⚠️  Erreur chargement cache: {e}")
                self.data = {}
        else:
            print(f"📂 Cache vide, nouveau fichier: {self.cache_file}")
    
    def save(self):
        """Save cache to file."""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️  Erreur sauvegarde cache: {e}")
    
    def get_property(self, url):
        """Get property from cache."""
        return self.data.get(url)
    
    def set_property(self, url, data):
        """Store property in cache."""
        self.data[url] = data
        self.save()
    
    def has_analysis(self, url):
        """Check if property has AI analysis in cache."""
        prop = self.get_property(url)
        return prop and 'analysis_ai' in prop
    
    def get_analysis(self, url):
        """Get AI analysis from cache."""
        prop = self.get_property(url)
        return prop.get('analysis_ai') if prop else None
    
    def set_analysis(self, url, analysis):
        """Store AI analysis in cache."""
        prop = self.get_property(url)
        if prop:
            prop['analysis_ai'] = analysis
            self.save()
    
    def get_status(self, url):
        """Get user status for property."""
        prop = self.get_property(url)
        return prop.get('user_status', '') if prop else ''
    
    def set_status(self, url, status):
        """Store user status in cache."""
        prop = self.get_property(url)
        if prop:
            prop['user_status'] = status
            self.save()
    
    def delete_property(self, url):
        """Remove property from cache to force re-parsing."""
        if url in self.data:
            del self.data[url]
            self.save()
            return True
        return False


def scan_leboncoin(city, query, pages=1):
    """Scan LeBonCoin for properties."""
    
    session = requests.Session()
    try:
        session.get("https://www.leboncoin.fr/", headers=HEADERS, timeout=10)
    except Exception:
        pass
    
    ad_urls = []
    
    for p in range(1, pages + 1):
        url = build_search_url(city, query, page=p)
        print(f"📡 Scraping page {p}: {url}")
        try:
            # Use requests with smart retry strategy for 403
            html = fetch(url, session=session, playwright_render=False)
            new_links = extract_ad_links_from_search(html)
            print(f"   ✅ {len(new_links)} annonces trouvées")
            
            # Si la page est vide, pas la peine de continuer
            if len(new_links) == 0:
                print(f"   ⏹️  Page vide, arrêt du scraping")
                break
            
            ad_urls.extend(new_links)
        except Exception as e:
            print(f"   ❌ Erreur: {e}")
    
    # Dedupe
    seen = set()
    ad_urls_filtered = []
    for u in ad_urls:
        if u not in seen:
            seen.add(u)
            ad_urls_filtered.append(u)
    
    return ad_urls_filtered, session

def parse_properties(ad_urls, session, cache, debug=False):
    """Parse properties and cache results."""
    
    session = requests.Session()
    try:
        session.get("https://www.leboncoin.fr/", headers=HEADERS, timeout=10)
    except Exception:
        pass
    
    properties = []
    
    for i, url in enumerate(ad_urls, 1):
        # Check cache first
        cached = cache.get_property(url)
        if cached:
            if debug:
                print(f"[{i}/{len(ad_urls)}] 📂 Cache: {cached.get('title', 'N/A')[:40]}")
                print(f"            URL: {url}")
            properties.append(cached)
            continue
        
        if debug:
            print(f"[{i}/{len(ad_urls)}] 🔍 Parsing: {cached.get('title', 'N/A')[:40] if cached else 'N/A'}")
            print(f"            URL: {url}")
        try:
            data = parse_ad_page(url, session=session)
            cache.set_property(url, data)
            properties.append(data)
        except Exception as e:
            if debug:
                print(f"            ❌ Erreur: {e}")
    
    return properties

def format_property_row(prop, idx, cache=None, status_emoji=""):
    """Format a property as a table row with headers."""
    # Same title width for all to keep alignment
    title_width = 69
    title = prop.get('title', 'N/A')[:title_width].ljust(title_width)
    
    price = f"{prop.get('price', 0):>8.0f}€".rjust(10)
    rent = f"{prop.get('monthly_rent', 0):>6.0f}€".rjust(8)
    yield_pct = f"{prop.get('gross_yield_pct', 0):>5.1f}%".rjust(7)
    
    # AI analysis status
    ai_status = "✅" if cache and cache.has_analysis(prop['url']) else "⏳"
    ai_status = ai_status.center(6)
    
    # AI verdict + avis combined emoji
    verdict_emoji = " "
    avis_emoji = ""
    score = ""
    if cache and cache.has_analysis(prop['url']):
        analysis = cache.get_analysis(prop['url'])
        if analysis:
            # Extract structured data from analysis (VERDICT, AVIS, SCORE tags)
            import re
            
            # Extract VERDICT
            verdict_match = re.search(r'\*{0,2}VERDICT\*{0,2}\s*:\s*(ACHETER|NEGOCIER|EVITER)', analysis, re.IGNORECASE)
            if verdict_match:
                verdict = verdict_match.group(1).upper()
                if verdict == "ACHETER":
                    verdict_emoji = "✅"
                elif verdict == "NEGOCIER":
                    verdict_emoji = "⚠️"
                elif verdict == "EVITER":
                    verdict_emoji = "❌"
            
            # Extract AVIS
            avis_match = re.search(r'\*{0,2}AVIS\*{0,2}\s*:\s*(TRES_BONNE|BONNE|MOYENNE|MAUVAISE)', analysis, re.IGNORECASE)
            if avis_match:
                avis = avis_match.group(1).upper()
                if avis == "TRES_BONNE":
                    avis_emoji = "🌟"
                elif avis == "BONNE":
                    avis_emoji = "👍"
                elif avis == "MOYENNE":
                    avis_emoji = "⚠️"
                elif avis == "MAUVAISE":
                    avis_emoji = "❌"
            
            # Extract SCORE
            score_match = re.search(r'\*{0,2}SCORE\*{0,2}\s*:\s*(\d+(?:[,\.]\d+)?)\s*/\s*10', analysis, re.IGNORECASE)
            if score_match:
                score = score_match.group(1).replace(',', '.')
            
            # Extract score: look for "/10" pattern
            import re
            score_match = re.search(r'(\d+(?:,\d+)?)\s*/\s*10', analysis)
            if score_match:
                score = score_match.group(1).replace(',', '.')
    
    # Combine verdict and avis emojis
    if verdict_emoji and verdict_emoji != " " and avis_emoji:
        # Both emojis present: no padding needed
        combined_verdict = (verdict_emoji + avis_emoji).ljust(5)
    elif verdict_emoji and verdict_emoji != " ":
        # Only verdict: pad to width
        combined_verdict = (verdict_emoji + avis_emoji).ljust(6)
    else:
        # Empty or only avis: pad to width
        combined_verdict = (verdict_emoji + avis_emoji).ljust(6) if avis_emoji else " ".ljust(6)
    score_col = score.rjust(5)
    
    # Status emoji
    status_col = status_emoji.ljust(6)
    
    # URL (shortened)
    url = prop.get('url', '')
    
    return f"{idx:3}. {title} | {price} | {rent} | {yield_pct} | {status_col} | {ai_status} | {combined_verdict} | {score_col} | {url}"


def interactive_menu(properties, cache):
    """Interactive menu to browse and analyze properties."""
    
    while True:
        # Display headers
        print("\n" + "="*220)
        print(f"📋 LISTE DES ANNONCES ({len(properties)} total)")
        print("="*220)
        
        # Column headers
        headers = f"{'N°':>3}. {'Titre':<69} | {'Prix':<10} | {'Loyer':<8} | {'Rend':<7} | {'Status':<6} | {'Analyse':<6} | {'Avis':<6} | {'Score':<5} | URL"
        print(headers)
        print("-"*220)
        
        for i, prop in enumerate(properties, 1):
            status = cache.get_status(prop['url']) if cache else ""
            row = format_property_row(prop, i, cache, status)
            print(row)
        
        print("\n" + "-"*220)
        print(f"Tapez le numero de l'annonce (1-{len(properties)}) pour analyser")
        print("Ou entrez une commande:")
        print("  's' - Scraper les annonces et mettre a jour le cache")
        print("  'q' - Quitter\n")
        print("LÉGENDE:")
        print("  📊 ANALYSE  : ✅ = en cache    | ⏳ = non analysée")
        print("  🎯 AVIS     : ✅🌟 = recommandé + excellent")
        print("              : ✅👍 = recommandé + bon")
        print("              : ⚠️⚠️ = neutre/à négocier")
        print("              : ❌❌ = à éviter")
        print("  👤 STATUS   : 👍 = intéressé   | 👎 = pas intéressé | 🤔 = hésitation")
        
        choice = input("\nChoix: ").strip().lower()
        
        if choice == 'q':
            print("\nAu revoir! 👋")
            break
        elif choice == 's':
            # Scrape option
            print(f"\n🔍 Scraping: {cache.args.query} à {cache.args.city}")
            ad_urls, session = scan_leboncoin(cache.args.city, cache.args.query, pages=cache.args.pages)
            
            if not ad_urls:
                print("❌ Aucune annonce trouvée")
                continue
            
            print(f"\n✅ {len(ad_urls)} annonces trouvees")
            
            # Parse properties
            print("\n📊 Analyse des annonces...")
            new_properties = parse_properties(ad_urls, session, cache, debug=cache.args.debug)
            
            # Save cache
            cache.save()
            
            # Update properties list
            properties = [p for p in cache.data.values() if p.get('price') and p.get('monthly_rent')]
            properties.sort(key=lambda x: x.get('gross_yield_pct', 0), reverse=True)
            
            print(f"✅ {len(properties)} annonces avec donnees valides\n")
            continue
                
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(properties):
                show_property_detail(properties[idx], cache)
            else:
                print("❌ Numero invalide")
        except ValueError:
            print("❌ Entree invalide")


def show_property_detail(prop, cache):
    """Show detailed analysis of a property."""
    
    url = prop['url']
    
    print("\n" + "="*120)
    print("📍 ANALYSE DÉTAILLÉE")
    print("="*120)
    
    # Display financial data
    print(f"\n📌 Titre: {prop.get('title', 'N/A')}")
    print(f"🔗 URL: {url}")
    
    print(f"\n💰 DONNÉES FINANCIÈRES:")
    print(f"  Prix d'achat: {prop.get('price', 'N/A')}€")
    print(f"  Loyer mensuel: {prop.get('monthly_rent', 'N/A')}€")
    print(f"  Rendement brut: {prop.get('gross_yield_pct', 'N/A')}%")
    print(f"  Rendement net: {prop.get('net_yield_pct', 'N/A')}%")
    
    # AI Analysis
    if not AI_AVAILABLE:
        print("\n⚠️  Analyse IA non disponible (Groq non installé)")
        return
    
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("\n⚠️  Analyse IA non disponible (GROQ_API_KEY non définie)")
        return
    
    print("\n" + "-"*120)
    print("Options:")
    print("  1. Afficher analyse en cache (si disponible)")
    print("  2. Générer analyse IA avec contenu complet de l'annonce")
    print("  3. Modifier mon avis (👍 intéressé, 👎 pas intéressé, 🤔 hésitation)")
    print("  4. Rafraîchir les données (re-parser l'annonce)")
    print("  5. Retour")
    
    choice = input("\nChoix: ").strip()
    
    if choice == '1':
        analysis = cache.get_analysis(url)
        if analysis:
            print("\n" + "="*120)
            print("🤖 ANALYSE (depuis cache)")
            print("="*120)
            print(analysis)
            print("\n" + "="*120)
            _back_to_menu = input("\nAppuyez sur Entrée pour retourner au menu...")
        else:
            print("❌ Pas d'analyse en cache pour cette annonce")
    
    elif choice == '2':
        print("\n📄 Extraction du contenu de l'annonce...")
        session = requests.Session()
        try:
            session.get("https://www.leboncoin.fr/", headers=HEADERS, timeout=10)
        except Exception:
            pass
        
        annonce_text = extract_annonce_text(url, session=session)
        
        print("\n🔄 Génération de l'analyse IA...")
        analysis = get_ai_analysis(prop, annonce_text=annonce_text)
        if analysis:
            cache.set_analysis(url, analysis)
            print("\n" + "="*120)
            print("🤖 ANALYSE IA (avec contenu complet)")
            print("="*120)
            print(analysis)
            print("\n" + "="*120)
            _back_to_menu = input("\nAppuyez sur Entrée pour retourner au menu...")
        else:
            print("❌ Erreur lors de la génération de l'analyse")
    
    elif choice == '3':
        print("\nQuel est votre avis?")
        print("  1. 👍 Intéressé")
        print("  2. 👎 Pas intéressé")
        print("  3. 🤔 Hésitation")
        print("  4. (vide) - Pas d'avis")
        
        status_choice = input("\nChoix: ").strip()
        
        status_map = {
            '1': '👍',
            '2': '👎',
            '3': '🤔',
            '4': ''
        }
        
        status_emoji = status_map.get(status_choice, '')
        if status_emoji is not None:
            cache.set_status(url, status_emoji)
            print(f"✅ Avis enregistré: {status_emoji if status_emoji else '(vide)'}")
    
    elif choice == '4':
        print("\n🔄 Rafraîchissement des données...")
        # Remove from cache to force re-parsing
        cache.delete_property(url)
        print("✅ Données supprimées du cache")
        
        # Re-parse the ad
        print("📊 Re-parsing de l'annonce...")
        session = requests.Session()
        try:
            session.get("https://www.leboncoin.fr/", headers=HEADERS, timeout=10)
        except Exception:
            pass
        
        # Parse the property again
        from scan_lbc import parse_ad_page
        updated_prop = parse_ad_page(url, session=session)
        
        if updated_prop:
            cache.set_property(url, updated_prop)
            print("\n✅ Données rafraîchies avec succès!")
            print(f"  Prix d'achat: {updated_prop.get('price', 'N/A')}€")
            print(f"  Loyer mensuel: {updated_prop.get('monthly_rent', 'N/A')}€")
            print(f"  Rendement brut: {updated_prop.get('gross_yield_pct', 'N/A')}%")
            print(f"  Rendement net: {updated_prop.get('net_yield_pct', 'N/A')}%")
            _back_to_menu = input("\nAppuyez sur Entrée pour retourner au menu...")
        else:
            print("❌ Erreur lors du re-parsing")
    
    print("\n" + "="*120)


def main():
    ap = argparse.ArgumentParser(description="Scanner interactif pour annonces LeBonCoin")
    ap.add_argument("--city", default="Nantes__47.23016052688833_-1.547806468993706_8804_10000", help="Localisation (defaut: Nantes avec coords GPS)")
    ap.add_argument("--query", default="loyer", help="Requete (defaut: loyer)")
    ap.add_argument("--pages", type=int, default=20, help="Pages a scanner (defaut: 20)")
    ap.add_argument("--cache", default="property_cache.json", help="Fichier cache (defaut: property_cache.json)")
    ap.add_argument("--debug", action="store_true", help="Afficher les details du scraping et du parsing")
    args = ap.parse_args()
    
    print("\n" + "="*120)
    print("🏠 SCANNER INTERACTIF LEBONCOIN - ANALYSE DE BIENS IMMOBILIERS")
    print("="*120)
    
    # Load or create cache
    cache = PropertyCache(args.cache)
    
    # Load from cache
    print(f"\n📂 Chargement du cache: {args.cache}")
    if not cache.data:
        print("❌ Cache vide. Utilisez l'option du menu pour scraper les annonces")
        sys.exit(1)
    
    print(f"✅ {len(cache.data)} annonces chargees du cache")
    properties = list(cache.data.values())
    
    # Filter properties with valid data
    properties = [p for p in properties if p.get('price') and p.get('monthly_rent')]
    
    if not properties:
        print("❌ Aucune annonce avec donnees valides")
        sys.exit(1)
    
    # Sort by gross yield
    properties.sort(key=lambda x: x.get('gross_yield_pct', 0), reverse=True)
    
    print(f"\n✅ {len(properties)} annonces avec donnees valides\n")
    
    # Store args in cache for later use
    cache.args = args
    
    # Interactive menu
    interactive_menu(properties, cache)
    
    print("\n" + "="*120)


if __name__ == "__main__":
    main()
