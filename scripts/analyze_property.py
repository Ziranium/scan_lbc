#!/usr/bin/env python3
"""Analyse détaillée d'un bien immobilier locatif à partir d'une URL LeBonCoin.

Usage:
  python3 scripts/analyze_property.py https://www.leboncoin.fr/ad/ventes_immobilieres/3110667700
  
Avec IA Groq:
  GROQ_API_KEY=your_key python3 scripts/analyze_property.py https://www.leboncoin.fr/ad/ventes_immobilieres/3110667700
"""

import argparse
import sys
import os
import json
import re
import requests
from bs4 import BeautifulSoup
from scan_lbc import parse_ad_page, HEADERS, fetch

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False


def format_currency(value):
    """Format a number as currency."""
    if value is None:
        return "N/A"
    return f"{value:,.2f}€".replace(',', ' ')


def extract_annonce_text(url, session=None):
    """Extract full text content from an annonce."""
    try:
        html = fetch(url, session=session)
        soup = BeautifulSoup(html, "lxml")
        
        # Get body text from ad
        body_text = ""
        script = soup.find('script', {'id': '__NEXT_DATA__'})
        if script:
            try:
                data = json.loads(script.string)
                body_text = data.get('props', {}).get('pageProps', {}).get('ad', {}).get('body', '')
            except:
                pass
        
        # Fallback to page text if body_text is empty
        if not body_text:
            body_text = soup.get_text(separator=" ", strip=True)
        
        return body_text[:2000]  # Limit to 2000 chars for API
    except Exception as e:
        return f"Erreur extraction: {e}"


def get_ai_analysis(property_data, annonce_text=None):
    """Get AI analysis using Groq API (free tier)."""
    if not GROQ_AVAILABLE:
        return None
    
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None
    
    try:
        client = Groq(api_key=api_key)
        
        # Prepare property data summary
        title = property_data.get('title', 'N/A')
        price = property_data.get('price')
        monthly_rent = property_data.get('monthly_rent')
        annual_charges = property_data.get('annual_charges') or 0
        taxe_annual = property_data.get('taxe_fonciere_annual') or 0
        gross_yield = property_data.get('gross_yield_pct')
        
        # Calculate financing info (20 ans, 3.09%, 0.15% assurance)
        cost_with_notary = price * 1.075 if price else 0  # 7.5% frais de notaires
        monthly_rate = 3.09 / 100 / 12
        insurance_rate = 0.15 / 100 / 12
        num_months = 20 * 12
        
        # Calculate monthly debt payment
        if price and monthly_rate > 0:
            monthly_payment = cost_with_notary * monthly_rate * (1 + monthly_rate) ** num_months / ((1 + monthly_rate) ** num_months - 1)
            monthly_insurance = cost_with_notary * insurance_rate
            monthly_debt = monthly_payment + monthly_insurance
        else:
            monthly_debt = 0
        
        property_summary = f"""Bien immobilier: {title}
Prix d'achat: {price}€
Prix avec frais notaires (7.5%): {cost_with_notary:.2f}€
Loyer mensuel: {monthly_rent}€
Loyer annuel: {monthly_rent * 12 if monthly_rent else 0}€
Charges annuelles: {annual_charges}€
Taxe fonciere annuelle: {taxe_annual}€
Rendement brut: {gross_yield}%

FINANCEMENT (20 ans, 3.09% + 0.15% assurance):
Mensualite emprunt: {monthly_debt:.2f}€
Difference loyer - emprunt: {(monthly_rent or 0) - monthly_debt:.2f}€"""
        
        # Build prompt with or without annonce text
        if annonce_text:
            prompt = f"""Tu es un expert en investissement immobilier locatif en France, specialise dans l'analyse de petites surfaces (studios, T1, T2) en zone urbaine.

Ton objectif est d'aider un investisseur a prendre une decision rationnelle et pragmatique.

Analyse l'annonce suivante a partir des donnees fournies.
Ne fais AUCUN calcul financier toi-meme : utilise uniquement les valeurs deja presentes.

=== DONNEES DE L'ANNONCE ===
{property_summary}

=== CONTENU COMPLET DE L'ANNONCE ===
{annonce_text}

=== TA MISSION ===

1. Resume le bien en une phrase claire.
2. Analyse la coherence du prix par rapport au marche (sans inventer de chiffres).
3. Identifie les points positifs pour un investissement locatif.
4. Identifie les points de vigilance / risques (juridiques, techniques, locatifs, copropriete).
5. Analyse la rentabilite fournie (brute et nette) et le cashflow.
6. Donne un avis global.
7. Donne un score global sur 10.
8. Conclus par une recommandation claire.

Sois factuel, synthetique, structure et oriente investisseur.
Evite toute speculation non justifiee.

=== FORMAT DE SORTIE OBLIGATOIRE ===
À la fin de ton analyse, ajoute exactement ces 3 lignes (remplace X par les valeurs):
VERDICT: [ACHETER|NEGOCIER|EVITER]
AVIS: [TRES_BONNE|BONNE|MOYENNE|MAUVAISE]
SCORE: X/10
"""
        else:
            prompt = f"""Tu es un expert en investissement immobilier locatif en France, specialise dans l'analyse de petites surfaces (studios, T1, T2) en zone urbaine.

Ton objectif est d'aider un investisseur a prendre une decision rationnelle et pragmatique.

Analyse l'annonce suivante a partir des donnees fournies.
Ne fais AUCUN calcul financier toi-meme : utilise uniquement les valeurs deja presentes.

=== DONNEES DE L'ANNONCE ===
{property_summary}

=== TA MISSION ===

1. Resume le bien en une phrase claire.
2. Analyse la coherence du prix par rapport au marche (sans inventer de chiffres).
3. Identifie les points positifs pour un investissement locatif.
4. Identifie les points de vigilance / risques (juridiques, techniques, locatifs, copropriete).
5. Analyse la rentabilite fournie (brute et nette) et le cashflow.
6. Donne un avis global.
7. Donne un score global sur 10.
8. Conclus par une recommandation claire.

Sois factuel, synthetique, structure et oriente investisseur.
Evite toute speculation non justifiee.

=== FORMAT DE SORTIE OBLIGATOIRE ===
À la fin de ton analyse, ajoute exactement ces 3 lignes (remplace X par les valeurs):
VERDICT: [ACHETER|NEGOCIER|EVITER]
AVIS: [TRES_BONNE|BONNE|MOYENNE|MAUVAISE]
SCORE: X/10
"""

        message = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=800 if annonce_text else 500,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        return message.choices[0].message.content
    
    except Exception as e:
        print(f"⚠️  Erreur IA: {e}")
        return None


def analyze_property(url):
    """Analyze a property in detail."""
    
    print("\n" + "="*80)
    print("ANALYSE DÉTAILLÉE - BIEN IMMOBILIER LOCATIF")
    print("="*80)
    
    # Fetch and parse the property data
    session = requests.Session()
    try:
        session.get("https://www.leboncoin.fr/", headers=HEADERS, timeout=10)
    except Exception:
        pass
    
    try:
        data = parse_ad_page(url, session=session)
    except Exception as e:
        print(f"❌ Erreur lors de la lecture de l'annonce: {e}")
        sys.exit(1)
    
    # Extract data
    title = data.get('title', 'N/A')
    price = data.get('price')
    monthly_rent = data.get('monthly_rent')
    annual_rent = data.get('annual_rent')
    monthly_charges = data.get('monthly_charges') or 0
    annual_charges = data.get('annual_charges') or 0
    taxe_annual = data.get('taxe_fonciere_annual') or 0
    gross_yield = data.get('gross_yield_pct')
    net_yield = data.get('net_yield_pct')
    
    # Display property info
    print(f"\n📍 BIEN IMMOBILIER")
    print(f"  Titre: {title}")
    print(f"  URL: {url}")
    
    print(f"\n💰 PRIX ET LOCATION")
    print(f"  Prix d'achat: {format_currency(price)}")
    print(f"  Loyer mensuel: {format_currency(monthly_rent)}")
    print(f"  Loyer annuel: {format_currency(annual_rent)}")
    
    print(f"\n📊 CHARGES ET FRAIS")
    print(f"  Charges mensuelles: {format_currency(monthly_charges if monthly_charges else 0)}")
    print(f"  Charges annuelles: {format_currency(annual_charges if annual_charges else 0)}")
    print(f"  Taxe foncière annuelle: {format_currency(taxe_annual if taxe_annual else 0)}")
    
    # Calculate additional metrics
    if price and monthly_rent:
        # Amortissement (payback period)
        amortissement = price / (monthly_rent * 12) if monthly_rent else None
        
        # Net rent after charges
        net_monthly_rent = (monthly_rent or 0) - (monthly_charges or 0)
        net_annual_rent = net_monthly_rent * 12
        
        # ROI calculations
        annual_income = annual_rent or 0
        annual_expenses = (annual_charges or 0) + (taxe_annual or 0)
        net_profit = annual_income - annual_expenses
        
        print(f"\n📈 RENDEMENTS")
        print(f"  Rendement brut: {gross_yield:.2f}%")
        print(f"  Rendement net: {net_yield:.2f}%")
        print(f"  Revenu annuel brut: {format_currency(annual_income)}")
        print(f"  Dépenses annuelles: {format_currency(annual_expenses)}")
        print(f"  Profit annuel net: {format_currency(net_profit)}")
        
        print(f"\n⏱️ AMORTISSEMENT")
        print(f"  Temps d'amortissement (années): {amortissement:.1f} ans")
        if amortissement:
            years = int(amortissement)
            months = int((amortissement - years) * 12)
            print(f"  Soit: {years} ans et {months} mois")
        
        print(f"\n💵 CASH FLOW MENSUEL")
        print(f"  Loyer mensuel: {format_currency(monthly_rent)}")
        print(f"  Charges mensuelles: {format_currency(monthly_charges if monthly_charges else 0)}")
        print(f"  Taxe foncière mensuelle: {format_currency((taxe_annual or 0) / 12)}")
        print(f"  Cash flow net mensuel: {format_currency(net_monthly_rent - (taxe_annual or 0) / 12)}")
        
        # Analysis and recommendations
        print(f"\n🎯 ANALYSE")
        
        if gross_yield >= 10:
            print(f"  ✅ Rendement très attractif (≥10%)")
        elif gross_yield >= 6:
            print(f"  ✅ Bon rendement (6-10%)")
        elif gross_yield >= 3:
            print(f"  ⚠️ Rendement moyen (3-6%)")
        else:
            print(f"  ❌ Rendement faible (<3%)")
        
        if amortissement < 10:
            print(f"  ✅ Amortissement rapide (<10 ans)")
        elif amortissement < 15:
            print(f"  ⚠️ Amortissement moyen (10-15 ans)")
        else:
            print(f"  ❌ Amortissement long (>15 ans)")
        
        if net_profit > 0:
            print(f"  ✅ Bien rentable (profit positif)")
        else:
            print(f"  ❌ Bien déficitaire (profit négatif)")
        
        # Price per m2 estimation (rough)
        # Try to extract surface from title
        import re
        match = re.search(r'(\d+)\s*m²', title)
        if match:
            surface = int(match.group(1))
            price_per_m2 = price / surface
            print(f"\n📐 SURFACE ET PRIX")
            print(f"  Surface: {surface}m²")
            print(f"  Prix au m²: {format_currency(price_per_m2)}")
    
    print("\n" + "="*80)


def main():
    ap = argparse.ArgumentParser(description="Analyse detaillee d'un bien immobilier locatif LeBonCoin")
    ap.add_argument("url", help="URL de l'annonce LeBonCoin (ex: https://www.leboncoin.fr/ad/ventes_immobilieres/3110667700)")
    ap.add_argument("--ai", action="store_true", help="Activer l'analyse IA avec Groq (requiert GROQ_API_KEY)")
    ap.add_argument("--full-content", action="store_true", help="Envoyer le contenu complet de l'annonce a l'IA (avec --ai)")
    args = ap.parse_args()
    
    analyze_property(args.url)
    
    # AI Analysis if requested
    if args.ai and GROQ_AVAILABLE:
        session = requests.Session()
        try:
            session.get("https://www.leboncoin.fr/", headers=HEADERS, timeout=10)
        except Exception:
            pass
        
        try:
            data = parse_ad_page(args.url, session=session)
            
            # Extract annonce text if full content requested
            annonce_text = None
            if args.full_content:
                print("\n📄 Extraction du contenu de l'annonce...")
                annonce_text = extract_annonce_text(args.url, session=session)
            
            ai_analysis = get_ai_analysis(data, annonce_text=annonce_text)
            
            if ai_analysis:
                print("\n" + "="*80)
                if args.full_content:
                    print("🤖 ANALYSE PAR INTELLIGENCE ARTIFICIELLE - AVEC CONTENU COMPLET (Groq)")
                else:
                    print("🤖 ANALYSE PAR INTELLIGENCE ARTIFICIELLE (Groq)")
                print("="*80)
                print(ai_analysis)
                print("="*80)
        except Exception as e:
            print(f"❌ Erreur lors de l'analyse IA: {e}")
    elif args.ai and not GROQ_AVAILABLE:
        print("\n⚠️  Groq non disponible. Installe-le avec: pip install groq")
    
    print()


if __name__ == "__main__":
    main()

